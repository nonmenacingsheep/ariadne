"""openWakeWord's train.py imports `generate_samples` from the folder named by
piper_sample_generator_path before it does anything, even when only training.
The clips come from make_clips.py instead, so this stands in and is never called."""


def generate_samples(*_args, **_kwargs):
    raise SystemExit("run make_clips.py first: train.py's own clip generation isn't used here")
