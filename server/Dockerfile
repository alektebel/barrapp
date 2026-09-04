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
COPY api/handler.py process.py deepseek.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.worker"]
