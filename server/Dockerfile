FROM public.ecr.aws/lambda/python:3.12

# Amazon Linux 2023 has wheels for NumPy 2.x. The 3.11 image is Amazon Linux 2
# and pip then tries to compile NumPy with no compiler.
RUN (microdnf install -y gcc gcc-c++ make python3-devel && microdnf clean all) \
    || (dnf install -y gcc gcc-c++ make python3-devel && dnf clean all) \
    || true

ENV BARRA_ROOT=/opt/barra
ENV BARRA_POSE_MODEL=/opt/barra/models/pose_landmarker_heavy.task
ENV PYTHONPATH=/opt/barra:${LAMBDA_TASK_ROOT}
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements-worker.txt ${LAMBDA_TASK_ROOT}/requirements-worker.txt
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir --only-binary=:all: -r ${LAMBDA_TASK_ROOT}/requirements-worker.txt

COPY vendor/barra /opt/barra
COPY api/handler.py process.py deepseek.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.worker"]
