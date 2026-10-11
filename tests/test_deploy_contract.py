"""What the worker image and the stack must agree on before a deploy.

Each test is a deploy that broke, or was about to:

  * 2026-09-12: the image shipped without `auth.py`/`chat.py`; every clip went
    to the dead-letter queue with `No module named 'auth'` while the deploy
    reported success.
  * 2026-10-11: `handler.py` imports `referral`, which the Dockerfile did not
    copy - the next deploy would have repeated 09-12 exactly.
  * every trace in production says `commit: unknown`, because the container
    has no `.git`, so no result could be tied to the code that produced it.

Static checks only: no docker, no AWS.
"""
from __future__ import annotations

import ast
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"
sys.path.insert(0, str(ROOT))

# What the worker container runs: CMD handler.worker, which imports process,
# which imports vision and the report writer.
WORKER_ENTRY = ["api/handler.py", "process.py"]


def _local_modules() -> dict[str, Path]:
    """Module name -> source file, for every module the server could import
    from its own tree (server/ and server/api/ both land in the task root)."""
    found: dict[str, Path] = {}
    for folder in (SERVER, SERVER / "api"):
        for f in folder.glob("*.py"):
            found.setdefault(f.stem, f)
    return found


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _worker_closure() -> set[str]:
    """Every server-local module the worker reaches, transitively."""
    local = _local_modules()
    todo = [SERVER / e for e in WORKER_ENTRY]
    seen: set[str] = set()
    while todo:
        f = todo.pop()
        if f.stem in seen:
            continue
        seen.add(f.stem)
        for name in _imports(f):
            if name in local and name not in seen:
                todo.append(local[name])
    return seen


def _dockerfile_copies() -> set[str]:
    """Module names the Dockerfile puts in the task root."""
    text = (SERVER / "Dockerfile").read_text().replace("\\\n", " ")
    copied: set[str] = set()
    local = _local_modules()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("COPY ") or "--from" in line:
            continue
        sources = line.split()[1:-1]
        for src in sources:
            if src.endswith("*.py"):
                folder = SERVER / src[:-len("*.py")]
                copied |= {f.stem for f in folder.glob("*.py")}
            elif src.endswith(".py"):
                copied.add(Path(src).stem)
    return copied & set(local)


class WorkerImageCarriesItsImports(unittest.TestCase):
    def test_every_module_the_worker_imports_is_copied(self):
        missing = _worker_closure() - _dockerfile_copies()
        self.assertEqual(missing, set(),
                         f"the worker imports {sorted(missing)} but the Dockerfile "
                         "does not copy them: every clip would fail at import time")


class StackDefinesWhatTheCodeRequires(unittest.TestCase):
    """`os.environ["X"]` raises KeyError at import time when X is unset."""

    def test_hard_env_reads_are_defined_in_the_template(self):
        template = (SERVER / "template.yaml").read_text()
        missing = []
        for rel in ("api/handler.py", "api/uploads.py", "api/sweeper.py"):
            for name in re.findall(r'os\.environ\["([A-Z_]+)"\]',
                                   (SERVER / rel).read_text()):
                if not re.search(rf"^\s+{name}:", template, re.M):
                    missing.append(f"{rel}: {name}")
        self.assertEqual(missing, [])


class ApiHasAStableName(unittest.TestCase):
    """The app talks to api.barrapp.fit, not to the API Gateway id: a phone
    could not resolve *.execute-api.amazonaws.com on 2026-10-11, and the id
    changes whenever the API is recreated."""

    def setUp(self):
        self.t = (SERVER / "template.yaml").read_text()

    def test_the_custom_domain_is_part_of_the_stack(self):
        for needle in ("Type: AWS::ApiGatewayV2::DomainName",
                       "Type: AWS::ApiGatewayV2::ApiMapping",
                       "EndpointType: REGIONAL", "Default: api.barrapp.fit"):
            self.assertIn(needle, self.t)

    def test_it_is_only_created_with_a_certificate(self):
        self.assertIn("HasApiDomain:", self.t)
        self.assertEqual(self.t.count("Condition: HasApiDomain"), 3)  # domain, mapping, output

    def test_the_dns_target_is_an_output(self):
        self.assertIn("ApiDomainTarget:", self.t)
        self.assertIn("RegionalDomainName", self.t)


class BuildIsStamped(unittest.TestCase):
    def setUp(self):
        from barra import provenance
        provenance.git_commit.cache_clear()
        self.addCleanup(provenance.git_commit.cache_clear)
        self.provenance = provenance

    def test_commit_comes_from_the_build_when_there_is_no_git(self):
        with mock.patch.dict(os.environ, {"BARRA_COMMIT": "abc1234"}), \
                mock.patch("subprocess.run", side_effect=FileNotFoundError("git")):
            self.assertEqual(self.provenance.git_commit(), "abc1234")

    def test_build_stamp_wins_over_a_checkout(self):
        # The image is what ran; a git tree that happens to be around is not.
        with mock.patch.dict(os.environ, {"BARRA_COMMIT": "abc1234"}):
            self.assertEqual(self.provenance.git_commit(), "abc1234")

    def test_without_stamp_or_git_it_still_says_unknown(self):
        env = {k: v for k, v in os.environ.items() if k != "BARRA_COMMIT"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("subprocess.run", side_effect=FileNotFoundError("git")):
            self.assertEqual(self.provenance.git_commit(), "unknown")

    def test_dockerfile_bakes_the_commit_into_the_image(self):
        docker = (SERVER / "Dockerfile").read_text()
        self.assertRegex(docker, r"ARG BARRA_COMMIT")
        self.assertRegex(docker, r"ENV BARRA_COMMIT=\$\{?BARRA_COMMIT\}?")

    def test_the_commit_stamp_survives_set_e_on_a_clean_tree(self):
        # Run deploy.sh's own lines, up to the stamp, in a throwaway clean repo.
        import subprocess
        import tempfile
        text = (SERVER / "deploy.sh").read_text()
        start = text.index("# Production was built from an uncommitted tree")
        end = text.index('echo "deploying commit $COMMIT"') + len('echo "deploying commit $COMMIT"')
        with tempfile.TemporaryDirectory() as d:
            git = ["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t"]
            subprocess.run(git[:3] + ["init", "-q"], check=True)
            subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True)
            out = subprocess.run(["bash", "-c", "set -euo pipefail\ncd \"$1\"\n" + text[start:end], "_", d],
                                 capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout, r"deploying commit [0-9a-f]{7}$")

    def test_deploy_passes_the_commit_and_refuses_a_dirty_tree(self):
        deploy = (SERVER / "deploy.sh").read_text()
        self.assertIn("--build-arg BARRA_COMMIT=", deploy)
        self.assertIn("git status --porcelain", deploy)


if __name__ == "__main__":
    unittest.main()
