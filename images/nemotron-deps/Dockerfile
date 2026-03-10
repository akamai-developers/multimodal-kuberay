FROM rayproject/ray-llm:2.54.0-py311-cu128

# Pre-install Nemotron Parse runtime_env dependencies so Ray workers
# skip the pip install on startup.  Versions are pinned to match
# rayservice-nemotron-parse.yaml.
RUN pip install --no-cache-dir \
    "numpy<2.0" \
    "cloudpickle>=3.1.0" \
    timm==1.0.22 \
    albumentations==2.0.8 \
    open_clip_torch
