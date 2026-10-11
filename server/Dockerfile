FROM public.ecr.aws/lambda/python:3.12

# Amazon Linux 2023 has wheels for NumPy 2.x. The 3.11 image is Amazon Linux 2
# and pip then tries to compile NumPy with no compiler.
#
# gcc etc. build any sdist that lacks a wheel. The rest are OpenCV/MediaPipe
# runtime loads: mediapipe pulls non-headless opencv-contrib-python, whose
# `cv2` dlopen()s libGL.so.1 (and glib/X11/gomp) at import time. The base image
# is minimal, so without these every clip fails with
# "libGL.so.1: cannot open shared object file" and the worker returns zero reps.
# Left to fail loudly: a package name typo here must abort the build, not ship a
# container that silently measures nothing.
RUN (dnf install -y gcc gcc-c++ make python3-devel \
        mesa-libGL mesa-libEGL glib2 libXext libXrender libX11 libSM libICE \
        fontconfig libgomp libpng \
     && dnf clean all) \
    || (microdnf install -y gcc gcc-c++ make python3-devel \
        mesa-libGL mesa-libEGL glib2 libXext libXrender libX11 libSM libICE \
        fontconfig libgomp libpng \
     && microdnf clean all)

ENV BARRA_ROOT=/opt/barra
ENV BARRA_POSE_MODEL=/opt/barra/models/pose_landmarker_heavy.task
ENV PYTHONPATH=/opt/barra:${LAMBDA_TASK_ROOT}
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements-worker.txt ${LAMBDA_TASK_ROOT}/requirements-worker.txt
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir --only-binary=:all: -r ${LAMBDA_TASK_ROOT}/requirements-worker.txt

COPY vendor/barra /opt/barra
# Every module handler.py imports, or the container starts and dies at
# import time with `No module named '<x>'` - which is exactly how the
# deploy of 2026-09-12 sent every clip to the dead-letter queue while
# reporting success. deploy.sh now smoke-invokes the image for this.
#
# The whole api/ folder rather than a list: the list is what went stale twice
# (auth on 09-12, referral on 10-11). tests/test_deploy_contract.py checks the
# worker's import closure against this file.
COPY api/*.py process.py report.py vision.py ${LAMBDA_TASK_ROOT}/

# Last, so a new commit does not invalidate the pip layer. Read by
# barra.provenance: every trace names the commit that produced it.
ARG BARRA_COMMIT=unknown
ENV BARRA_COMMIT=${BARRA_COMMIT}

CMD ["handler.worker"]
