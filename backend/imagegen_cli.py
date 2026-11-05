"""ImageGen from a terminal — one generation through the plugin engine, for scripts and coding agents.

The plugin registers it as a Hermes subcommand, so Hermes loads the profile and its secrets first::

    hermes -p my-profile imagegen --prompt-file prompt.txt \
        --ref photo-a.jpg --ref photo-b.jpg --aspect 4:5 --out ./images --name hero

``python imagegen_cli.py ...`` with the Hermes venv Python still works, with the current process's
environment only: it never loads a profile or its ``.env``.

The engine is the one the ImageGen screen and the chat provider use: the provider
and model follow ImageGen's own choice unless ``--provider``/``--model`` are given
(``--list`` prints the providers it can use now; ``--list <provider>`` their models),
references may live in any folder (they are copied into the plugin's reference
store first), and every image is kept in the gallery and counted in the budget.
The result prints as JSON; failures print ``ERROR [code]: message`` and exit 1.

``--batch jobs.jsonl --workers 16`` runs many generations at once in one process. Each line is a JSON
object with ``prompt`` and ``name``, and optionally ``refs``, ``aspect``, ``out`` and ``label``. A job
whose file already exists is skipped, so a repeated run only does what is missing; ``--replace``
generates it again over the old file. Each job prints one JSON line when it ends, and the last line is
the summary; a failed job never stops the others. ``--spend`` prints this month's spend by label.

``--edit photo.png --prompt "..."`` edits an image and keeps every pixel the model did not change: the
source goes out without loss and only the changed area returns over it. ``--mask area.png`` (white on the
area) fixes that area and ``--whole`` takes the model's whole answer. Batch lines take ``edit`` and ``mask``.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

_PLUGIN_HOME = os.path.dirname(os.path.abspath(__file__))
# Larger photos only slow the upload (measured 11 s against 18.6 s per image), so they are reduced to this side.
_REF_MAX_SIDE = 2048
_RETRY_BASE_SECONDS = 5
_RATE_LIMIT_BASE_SECONDS = 20
_RETRY_MAX_SECONDS = 120


DESCRIPTION = "Generate images with the ImageGen engine."
_PROFILE_HINT = ("ERROR [profile.flag]: --profile was removed; run `hermes -p <profile> imagegen ...` "
                 "so Hermes loads the profile and its keys")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Every option of the command; shared by ``hermes imagegen`` and ``python imagegen_cli.py``."""
    parser.add_argument("--list", nargs="?", const="", default=None, metavar="PROVIDER",
                        help="print the providers ImageGen can use now, or one provider's models, and exit")
    text = parser.add_mutually_exclusive_group()
    text.add_argument("--prompt", help="the prompt text")
    text.add_argument("--prompt-file", type=Path, help="a UTF-8 file with the prompt text")
    parser.add_argument("--ref", action="append", default=[], type=Path, help="a reference image (repeatable)")
    parser.add_argument("--edit", type=Path, help="the image to edit, keeping what the model did not change")
    parser.add_argument("--mask", type=Path, help="with --edit: an image with the area to change in white")
    parser.add_argument("--whole", action="store_true", help="with --edit: take the model's whole answer")
    parser.add_argument("--aspect", default="1:1", help="aspect ratio such as 1:1, 4:5 or 16:9 (default 1:1)")
    parser.add_argument("--provider", default="", help="provider id; default: ImageGen's own choice")
    parser.add_argument("--model", default="", help="model id; default: the provider's default model")
    parser.add_argument("--resolution", default="1K", help="1K, 2K or 4K where the model offers it")
    parser.add_argument("--count", type=int, default=1, help="number of images (default 1)")
    parser.add_argument("--out", type=Path, help="folder that receives a copy of each image")
    parser.add_argument("--name", default="imagegen", help="file name stem (default imagegen)")
    parser.add_argument("--replace", action="store_true",
                        help="overwrite the file of the same name; with --batch, generate existing files again")
    parser.add_argument("--label", default="", help="client or project recorded with this run's spend")
    parser.add_argument("--spend", action="store_true", help="print this month's spend by label and exit")
    parser.add_argument("--ref-max-side", type=int, default=_REF_MAX_SIDE,
                        help=f"reduce longer references to this side before sending; 0 sends them as they are "
                             f"(default {_REF_MAX_SIDE})")
    parser.add_argument("--retries", type=int, default=0,
                        help="extra attempts after a provider failure, with a growing wait; each attempt may be "
                             "billed (default 0)")
    # Kept only to explain the move to ``hermes -p``; the plugin never loads a profile itself.
    parser.add_argument("--profile", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--batch", type=Path, help="a JSONL file with one generation per line, run at the same time")
    parser.add_argument("--workers", type=int, default=8,
                        help="generations at the same time with --batch (default 8; openai-codex was measured at 32)")


def _check(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.profile is not None:
        raise SystemExit(_PROFILE_HINT)
    if args.batch and (args.prompt or args.prompt_file or args.ref):
        parser.error("--batch takes its prompts and references from the file")
    if args.batch and args.edit:
        parser.error("--batch takes the image to edit from the file")
    if (args.mask or args.whole) and not (args.edit or args.batch):
        parser.error("--mask and --whole need --edit")
    reads_only = args.list is not None or args.spend
    if not reads_only and not (args.prompt or args.prompt_file or args.batch):
        parser.error("one of --prompt, --prompt-file, --batch, --list or --spend is required")
    if not reads_only and args.out is None:
        parser.error("--out is required to generate")


def _parse(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="imagegen_cli", description=DESCRIPTION)
    add_arguments(parser)
    args = parser.parse_args(argv)
    _check(parser, args)
    return args


def _list(provider: str) -> Any:
    """The providers ImageGen can use now with their default model, or the models of one provider."""
    from imagegen_engine.providers_catalog import available_providers

    providers = available_providers()
    if not provider:
        return [{"provider": p["name"], "name": p.get("display_name", p["name"]),
                 "default_model": p.get("default_model", ""), "models": len(p["models"]),
                 "recommended": bool(p.get("recommended"))} for p in providers]
    entry = next((p for p in providers if p["name"] == provider), None)
    if entry is None:
        raise SystemExit(f"ERROR [provider.unavailable]: {provider!r} is not available; run --list to see the providers")
    return [{"model": m.get("id") or m.get("model"), "name": m.get("display", "")} for m in entry["models"]]


def _add_hermes_source() -> None:
    """Put the Hermes checkout on the path, as Hermes does for itself; the venv's editable finder may miss newer modules."""
    try:
        import hermes_constants
    except ImportError:  # outside Hermes only the plugin's own providers can run
        return
    source = os.path.dirname(os.path.abspath(hermes_constants.__file__))
    if source not in sys.path:
        sys.path.insert(0, source)


@lru_cache(maxsize=32)  # a batch often sends the same photos with every job
def _reference_bytes(path: Path, max_side: int = _REF_MAX_SIDE) -> bytes:
    """The bytes to send: the file itself, or a reduced copy when it is long or over the upload limit."""
    from imagegen_engine import image_input

    data = path.read_bytes()
    over_limit = len(data) > image_input.MAX_IMAGE_BYTES
    side = max_side if max_side > 0 else _REF_MAX_SIDE
    if max_side <= 0 and not over_limit:
        return data
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) <= side and not over_limit:
                return data
            transparent = "A" in image.getbands() or "transparency" in image.info
            image = ImageOps.exif_transpose(image).convert("RGBA" if transparent else "RGB")
            image.thumbnail((side, side), Image.LANCZOS)
            out = io.BytesIO()
            image.save(out, "PNG") if transparent else image.save(out, "JPEG", quality=90)
    except (ImportError, OSError):  # no Pillow, or not an image it reads; the store gives the real error
        return data
    return out.getvalue()


def _store_references(paths: List[Path], max_side: int = _REF_MAX_SIDE) -> List[str]:
    from imagegen_engine import store

    stored = []
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"ERROR [refs.not_found]: reference image not found: {path}")
        try:
            stored.append(str(store.save_reference(_reference_bytes(path, max_side))))
        except ValueError as exc:
            raise SystemExit(f"ERROR [refs.invalid]: {path}: {exc}") from exc
    return stored


def _store_edit_source(path: Path) -> str:
    """The image to edit, whole: only a file over the upload limit is written again, at top quality."""
    from imagegen_engine import edit_merge, image_input, store

    if not path.is_file():
        raise SystemExit(f"ERROR [refs.not_found]: image to edit not found: {path}")
    data = path.read_bytes()
    try:
        if len(data) > image_input.MAX_IMAGE_BYTES:
            data = edit_merge._encode(edit_merge._load(data))
        return str(store.save_reference(data))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR [refs.invalid]: {path}: {exc}") from exc


def _free_target(folder: Path, stem: str, suffix: str) -> Path:
    """A path in ``folder`` that does not overwrite an earlier image."""
    target, n = folder / f"{stem}{suffix}", 2
    while target.exists():
        target, n = folder / f"{stem}-{n}{suffix}", n + 1
    return target


def _replace_target(folder: Path, stem: str, suffix: str, index: int) -> Path:
    """The fixed path of the image at ``index``, so a new run overwrites the earlier one."""
    return folder / (f"{stem}{suffix}" if index == 0 else f"{stem}-{index + 1}{suffix}")


def _retryable(exc: Exception) -> bool:
    from imagegen_engine import gen_service
    from imagegen_engine.errors import ImageGenError

    if isinstance(exc, ImageGenError):
        return exc.code in ("provider.failed", "model.no_image")
    return gen_service._is_transient_error(exc)


def _retry_delay(exc: Exception, attempt: int) -> float:
    """A wait that doubles at each attempt, longer on a rate limit; the random part keeps workers apart."""
    text = f"{exc} {getattr(exc, 'params', {}).get('detail', '')} {getattr(exc, 'code', '')}".lower()
    limited = any(mark in text for mark in ("429", "rate limit", "rate_limit", "too many requests"))
    base = _RATE_LIMIT_BASE_SECONDS if limited else _RETRY_BASE_SECONDS
    return min(_RETRY_MAX_SECONDS, base * 2 ** attempt) * random.uniform(1, 1.25)


def _generate(args: argparse.Namespace) -> Dict[str, Any]:
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else args.prompt
    return _generate_one(args, prompt, args.ref, args.aspect, args.out, args.name, args.label, args.edit, args.mask)


def _resolve_provider(args: argparse.Namespace) -> tuple[str, str]:
    """The provider and model of a run; listing the providers takes about 3 s of CPU, so a batch does it once."""
    from imagegen_engine.providers_catalog import available_providers, resolve_target

    if args.provider:
        model = args.model or next(
            (p.get("default_model", "") for p in available_providers() if p["name"] == args.provider), "")
        target = (args.provider, model)
    else:
        target = resolve_target(args.model)
        if target is None:
            raise SystemExit("ERROR [provider.unavailable]: ImageGen has no image provider it can use")
    provider, model = target
    if not model:
        raise SystemExit(f"ERROR [model.missing]: {provider!r} has no default model here; pass --model "
                         f"(see --list {provider})")
    return provider, model


def _generate_one(args: argparse.Namespace, prompt: str, refs: List[Path], aspect: str, out: Path,
                  name: str, label: str = "", edit: Path | None = None, mask: Path | None = None) -> Dict[str, Any]:
    from imagegen_engine import image_input, store
    from imagegen_engine.generation_artifacts import InlineJob, build_generation_job
    from imagegen_engine.operations import build_operation

    provider, model = _resolve_provider(args)
    body = {"prompt": prompt, "provider": provider, "model": model, "aspectRatio": aspect,
            "resolution": args.resolution, "numImages": max(1, args.count),
            "referenceImages": _store_references(refs, args.ref_max_side), "config": {"source": "cli"}}
    if edit:
        base = _store_edit_source(edit)
        kind = "inpaint" if mask else "edit"
        body = {**body, "keepUnchanged": not args.whole, "images": [base, *body["referenceImages"]], "baseImage": base,
                **({"maskImage": _store_edit_source(mask)} if mask else {})}
    store.spend_label.set(label)
    for attempt in range(max(0, args.retries) + 1):
        try:
            run = build_operation(kind, body) if edit else build_generation_job(body)
            result = run(InlineJob("cli"))
            break
        except Exception as exc:  # noqa: BLE001 — a provider may raise its own transient error
            if not _retryable(exc) or attempt >= args.retries:
                raise
            time.sleep(_retry_delay(exc, attempt))
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for index, image in enumerate(result.get("images") or []):
        source = Path(image_input.resolve_served_image(image))
        suffix = source.suffix or ".png"
        target = _replace_target(out, name, suffix, index) if args.replace else _free_target(out, name, suffix)
        shutil.copyfile(source, target)
        files.append(str(target))
    return {"files": files, "provider": result.get("provider", provider), "model": result.get("model", model),
            "references_used": result.get("references_used", 0), "gallery_ids": result.get("gallery_ids") or [],
            "warnings": result.get("warnings") or [], **({"merge": result["merge"]} if "merge" in result else {})}


def _read_jobs(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Every job of the batch file, checked before the first generation spends anything."""
    jobs: List[Dict[str, Any]] = []
    seen = set()
    for number, line in enumerate(args.batch.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError as exc:
            raise SystemExit(f"ERROR [batch.invalid]: line {number} is not JSON: {exc}") from exc
        if not isinstance(raw, dict) or not raw.get("prompt") or not raw.get("name"):
            raise SystemExit(f"ERROR [batch.invalid]: line {number} needs prompt and name")
        out = Path(raw.get("out") or args.out)
        refs = [Path(ref) for ref in raw.get("refs") or []]
        edit, mask = (Path(raw[key]) if raw.get(key) else None for key in ("edit", "mask"))
        missing = next((ref for ref in (*refs, edit, mask) if ref and not ref.is_file()), None)
        if missing:
            raise SystemExit(f"ERROR [refs.not_found]: line {number}: reference image not found: {missing}")
        if (out, raw["name"]) in seen:
            raise SystemExit(f"ERROR [batch.invalid]: line {number} repeats the name {raw['name']!r}")
        seen.add((out, raw["name"]))
        jobs.append({"prompt": raw["prompt"], "name": raw["name"], "refs": refs, "out": out,
                     "aspect": raw.get("aspect") or args.aspect, "label": raw.get("label") or args.label,
                     "edit": edit, "mask": mask})
    return jobs


def _batch_job(args: argparse.Namespace, job: Dict[str, Any]) -> Dict[str, Any]:
    from imagegen_engine.errors import ImageGenError

    report: Dict[str, Any] = {"name": job["name"]}
    try:
        result = _generate_one(args, job["prompt"], job["refs"], job["aspect"], job["out"], job["name"], job["label"],
                               job["edit"], job["mask"])
        report.update(status="ok", files=result["files"], warnings=result["warnings"])
    except ImageGenError as exc:
        report.update(status="failed", error=f"[{exc.code}] {exc.message}")
    except (Exception, SystemExit) as exc:  # one bad job never stops the rest of the batch
        report.update(status="failed", error=str(exc))
    return report


def _batch(args: argparse.Namespace) -> int:
    started = time.time()
    counts = {"ok": 0, "skipped": 0, "failed": 0}
    pending = []
    jobs = _read_jobs(args)
    args.provider, args.model = _resolve_provider(args)
    for job in jobs:
        if (not args.replace and job["out"].is_dir()
                and any(p.stem == job["name"] and p.is_file() for p in job["out"].iterdir())):
            counts["skipped"] += 1
            print(json.dumps({"name": job["name"], "status": "skipped"}), flush=True)
        else:
            pending.append(job)
    with ThreadPoolExecutor(max(1, args.workers)) as pool:
        for future in as_completed([pool.submit(_batch_job, args, job) for job in pending]):
            report = future.result()
            counts[report["status"]] += 1
            print(json.dumps(report), flush=True)
    print(json.dumps({**counts, "seconds": round(time.time() - started, 1)}), flush=True)
    return 1 if counts["failed"] else 0


def setup_hermes_command(parser: argparse.ArgumentParser) -> None:
    """``setup_fn`` of ``ctx.register_cli_command``: the options of ``hermes imagegen``."""
    add_arguments(parser)
    parser.set_defaults(_imagegen_parser=parser)


def run_hermes_command(args: argparse.Namespace) -> int:
    """``handler_fn`` of ``hermes imagegen``; Hermes has already loaded the profile chosen with ``-p``."""
    _check(args._imagegen_parser, args)
    return _run(args)


def main(argv: List[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    _add_hermes_source()
    return _run(args)


def _run(args: argparse.Namespace) -> int:
    if _PLUGIN_HOME not in sys.path:
        sys.path.insert(0, _PLUGIN_HOME)
    from imagegen_engine.errors import ImageGenError

    if args.spend:
        from imagegen_engine import store

        print(json.dumps(store.spend_report(), ensure_ascii=False, indent=2))
        return 0
    if args.batch and args.list is None:
        return _batch(args)
    try:
        result = _list(args.list) if args.list is not None else _generate(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ImageGenError as exc:
        print(f"ERROR [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
