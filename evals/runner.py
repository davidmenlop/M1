"""Runner de evals: corre el dataset por el pipeline real y calcula métricas.

Uso:
    python evals/runner.py --provider mock                       # sin claves, humo
    python evals/runner.py --provider openai --prompt v2         # split dev por defecto
    python evals/runner.py --provider anthropic --repeat 3       # promedio de 3 corridas
    python evals/runner.py --provider openai --split holdout     # solo para confirmar al ganador
    python evals/runner.py --compare evals/results/*.json        # tabla markdown

Solo usa casos con label_status=validated. No escribe en data/metrics.jsonl: el resultado
completo va a evals/results/<fecha>_<proveedor>-<modelo>_<prompt>_<split>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import CATEGORIES, DATASET_PATH, DatasetError, load_dataset, validate  # noqa: E402
from evals.metrics import aggregate, check_thresholds, compute  # noqa: E402
from src.config import REPO_ROOT, ConfigError, load_model_config, load_settings  # noqa: E402
from src.guardrails import GuardrailConfigError, Guardrails  # noqa: E402
from src.pipeline import TriagePipeline  # noqa: E402
from src.prompts import PROMPTS_DIR, PromptError, load_prompt  # noqa: E402
from src.providers.base import ProviderFatalError, ProviderUnavailable  # noqa: E402
from src.providers.factory import build_provider  # noqa: E402

RESULTS_DIR = REPO_ROOT / "evals" / "results"
CONFIRM_ABOVE_USD = 0.50
EST_OUTPUT_TOKENS = 150


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False).stdout.strip()
        except OSError:
            return ""
    return {"commit": run("rev-parse", "--short", "HEAD") or None, "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


def select_cases(cases: list[dict[str, Any]], split: str, ids: list[str] | None) -> tuple[list[dict], list[str]]:
    pool = [c for c in cases if split == "all" or c["split"] == split]
    if ids:
        wanted = set(ids)
        missing = sorted(wanted - {c["id"] for c in pool})
        if missing:
            raise DatasetError(f"casos inexistentes en el split {split}: {missing}")
        pool = [c for c in pool if c["id"] in wanted]
    skipped = [c["id"] for c in pool if c["label_status"] != "validated"]
    return [c for c in pool if c["label_status"] == "validated"], skipped


def estimate_cost(cases: list[dict], prompt, model, repeat: int) -> float:
    input_tokens = sum(len("".join(prompt.render(c["input"]))) / 4 for c in cases)
    output_tokens = EST_OUTPUT_TOKENS * len(cases)
    per_run = (input_tokens * model.input_per_1m_usd + output_tokens * model.output_per_1m_usd) / 1_000_000
    return per_run * repeat


def run_case(pipeline: TriagePipeline, case: dict[str, Any]) -> dict[str, Any]:
    result = pipeline.run(case["input"])
    response = result.response
    return {
        "id": case["id"],
        "difficulty": case["difficulty"],
        "tags": case["tags"],
        "expected": case["expected_category"],
        "predicted": str(response.category),
        "confidence": response.confidence,
        "answer": response.answer,
        "actions": list(response.actions),
        "expected_actions": case["expected_actions"],
        "answer_keywords": case["answer_keywords"],
        "success": result.success,
        "attempts": result.attempts,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "token_source": result.token_source,
        "cost_usd": result.cost_usd,
        "latency_s": round(result.latency_s, 4),
        "error": result.error,
        "guard": result.guard.to_dict() if result.guard else None,
    }


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def _fmt(metric: Any, kind: str = "pct") -> str:
    if metric is None:
        return "—"
    if isinstance(metric, dict):
        mean, std = metric["mean"], metric["std"]
        if kind == "pct":
            return f"{mean:.0%} ±{std:.0%}"
        if kind == "usd":
            return f"{mean:.5f} ±{std:.5f}"
        return f"{mean:.3f} ±{std:.3f}"
    if kind == "pct":
        return f"{metric:.0%}"
    if kind == "usd":
        return f"{metric:.5f}"
    return f"{metric:.3f}"


def print_report(meta: dict[str, Any], summary: dict[str, Any], last: dict[str, Any], checks: dict) -> None:
    print(f"\n## {meta['provider']} / {meta['model_id']} · prompt {meta['prompt_version']} · split {meta['split']} · "
          f"{summary['n']} casos × {summary['runs']} corrida(s)\n")
    rows = [
        ("schema válido (post-retry)", _fmt(summary["schema_valid_rate"])),
        ("válido al primer intento", _fmt(summary["first_try_valid_rate"])),
        ("retry rate", _fmt(summary["retry_rate"])),
        ("accuracy", _fmt(summary["accuracy"])),
        ("macro-F1", _fmt(summary["macro_f1"], "num")),
        ("recall mínimo por clase", _fmt(summary["min_class_recall"])),
        ("action score", _fmt(summary["action_score"], "num")),
        ("cobertura de keywords en answer", _fmt(summary["answer_keyword_coverage"])),
        ("Brier (menor es mejor)", _fmt(summary["brier"], "num")),
        ("confidence media en aciertos", _fmt(summary["mean_confidence_correct"], "num")),
        ("confidence media en errores", _fmt(summary["mean_confidence_wrong"], "num")),
        ("costo medio por request (USD)", _fmt(summary["mean_cost_usd"], "usd")),
        ("costo total (USD)", _fmt(summary["total_cost_usd"], "usd")),
        ("latencia p50 / p95 (s)", f"{_fmt(summary['latency_p50_s'], 'num')} / {_fmt(summary['latency_p95_s'], 'num')}"),
    ]
    if summary.get("guard_overhead_p95_ms") is not None:
        rows += [
            ("guardrail: entradas bloqueadas", _fmt(summary["guard_blocked_rate"])),
            ("guardrail: entradas saneadas", _fmt(summary["guard_input_sanitized_rate"])),
            ("guardrail: salidas modificadas", _fmt(summary["guard_output_modified_rate"])),
            ("guardrail: overhead p95 (ms)", _fmt(summary["guard_overhead_p95_ms"], "num")),
        ]
    else:
        rows.append(("guardrails", "desactivados"))
    width = max(len(r[0]) for r in rows)
    for label, text in rows:
        print(f"  {label:<{width}}  {text}")

    label = "última corrida" if summary["runs"] > 1 else "corrida"
    print(f"\nPor clase ({label}):")
    print(f"  {'clase':<10} {'n':>3} {'precision':>10} {'recall':>8} {'f1':>6}")
    for c, row in last["per_class"].items():
        print(f"  {c:<10} {row['support']:>3} {row['precision']:>10.2f} {row['recall']:>8.2f} {row['f1']:>6.2f}")

    print(f"\nMatriz de confusión ({label}; filas = esperado, columnas = predicho):")
    print("  " + " " * 10 + "".join(f"{c[:9]:>10}" for c in CATEGORIES))
    for e in CATEGORIES:
        print(f"  {e:<10}" + "".join(f"{last['confusion_matrix'][e][p]:>10}" for p in CATEGORIES))

    print(f"\nAccuracy por dificultad ({label}): "
          + ", ".join(f"{k} {_pct(v['accuracy'])} (n={v['n']})" for k, v in last["accuracy_by_difficulty"].items()))
    if last["misclassified"]:
        print("Mal clasificados: " + ", ".join(f"{m['id']} ({m['expected']}→{m['predicted']})" for m in last["misclassified"]))
    if last["errors"]:
        print("Fallback (sin JSON válido): " + ", ".join(last["errors"]))

    print("\nUmbrales de aceptación:")
    for key, check in checks.items():
        mark = "✓" if check["passed"] else "✗"
        op = "<" if key == "mean_cost_usd" else "≥"
        print(f"  {mark} {key} {op} {check['limit']}  (observado: {check['observed']:.4g})")


def compare(paths: list[Path]) -> int:
    header = ("| corrida | proveedor / modelo | prompt | split | casos | schema | retry | accuracy | macro-F1 "
              "| recall mín | action | Brier | USD/req | p95 s |")
    print(header)
    print("|---" * (header.count("|") - 1) + "|")
    for path in sorted(paths):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta, s = data["meta"], data["summary"]
        print(
            f"| {path.stem.split('_')[0]} | {meta['provider']} / {meta['model_id']} | {meta['prompt_version']} "
            f"| {meta['split']} | {s['n']}×{s['runs']} | {_fmt(s['schema_valid_rate'])} | {_fmt(s['retry_rate'])} "
            f"| {_fmt(s['accuracy'])} | {_fmt(s['macro_f1'], 'num')} | {_fmt(s['min_class_recall'])} "
            f"| {_fmt(s['action_score'], 'num')} | {_fmt(s['brier'], 'num')} | {_fmt(s['mean_cost_usd'], 'usd')} "
            f"| {_fmt(s['latency_p95_s'], 'num')} |"
        )
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python evals/runner.py", description="Suite de evals del triage.")
    parser.add_argument("--provider", help="mock | openai | anthropic (por defecto: DEFAULT_PROVIDER)")
    parser.add_argument("--model", default="default", help="clave del modelo en config/providers.yaml")
    parser.add_argument("--prompt", help="versión del prompt (por defecto: DEFAULT_PROMPT_VERSION)")
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    parser.add_argument("--repeat", type=int, default=1, help="corridas repetidas para medir varianza")
    parser.add_argument("--ids", nargs="+", help="correr solo estos casos (depuración)")
    parser.add_argument("--no-save", action="store_true", help="no guardar el JSON de resultados")
    parser.add_argument("--no-guardrails", action="store_true", help="corre sin guardrails (para medir su efecto)")
    parser.add_argument("--yes", action="store_true", help=f"no pedir confirmación sobre USD {CONFIRM_ABOVE_USD}")
    parser.add_argument("--compare", nargs="+", type=Path, metavar="RESULTADO", help="tabla comparativa de resultados guardados")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.compare:
        return compare(args.compare)
    if args.repeat < 1:
        print("error: --repeat debe ser >= 1", file=sys.stderr)
        return 2

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")

    provider_name = args.provider or settings.default_provider
    prompt_version = args.prompt or settings.default_prompt_version
    try:
        cases_all = load_dataset()
        report = validate(cases_all)
        if not report.ok:
            raise DatasetError("el dataset tiene errores; corré python evals/validate_dataset.py")
        cases, skipped = select_cases(cases_all, args.split, args.ids)
        provider = build_provider(provider_name)
        model = load_model_config(provider_name, args.model)
        prompt = load_prompt(prompt_version)
        guardrails = None if args.no_guardrails else Guardrails.from_config()
    except (DatasetError, ProviderUnavailable, ConfigError, PromptError, GuardrailConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if skipped:
        print(f"aviso: se excluyen {len(skipped)} casos sin validar: {', '.join(skipped)}", file=sys.stderr)
    if not cases:
        print("error: no hay casos validados en la selección", file=sys.stderr)
        return 2
    if args.split in ("holdout", "all"):
        print("aviso: el holdout solo confirma al ganador; no lo uses para elegir (ADR-022)", file=sys.stderr)

    estimate = estimate_cost(cases, prompt, model, args.repeat)
    print(f"{len(cases)} casos × {args.repeat} corrida(s) con {provider_name}/{model.id}, prompt {prompt_version}. "
          f"Costo estimado: USD {estimate:.4f}", file=sys.stderr)
    if estimate > CONFIRM_ABOVE_USD and not args.yes:
        print(f"error: el costo estimado supera USD {CONFIRM_ABOVE_USD}; repetí con --yes para confirmar", file=sys.stderr)
        return 2

    pipeline = TriagePipeline(provider=provider, model=model, prompt=prompt,
                              max_retries=settings.max_retries, timeout_s=settings.request_timeout_s,
                              guardrails=guardrails)
    runs, run_cases = [], []
    try:
        for number in range(1, args.repeat + 1):
            results = []
            for position, case in enumerate(cases, start=1):
                row = run_case(pipeline, case)
                results.append(row)
                mark = "✓" if row["predicted"] == row["expected"] else "✗"
                print(f"  [{number}/{args.repeat}] {position:>2}/{len(cases)} {row['id']:<8} {mark} "
                      f"{row['expected']:<9} → {row['predicted']:<9} intentos={row['attempts']} {row['latency_s']:.2f}s",
                      file=sys.stderr)
            runs.append(compute(results))
            run_cases.append(results)
    except ProviderFatalError as exc:
        print(f"error: el proveedor rechazó la solicitud; la corrida se aborta sin guardar: {exc}", file=sys.stderr)
        return 2

    summary = aggregate(runs)
    checks = check_thresholds(summary)
    prompt_file = next(PROMPTS_DIR.glob(f"{prompt_version}_*.yaml"))
    meta = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": provider_name,
        "model_key": args.model,
        "model_id": model.id,
        "temperature": model.temperature,
        "effort": model.effort,
        "prompt_version": prompt_version,
        "prompt_file": prompt_file.name,
        "prompt_sha256": _sha256(prompt_file),
        "dataset_sha256": _sha256(DATASET_PATH),
        "split": args.split,
        "case_ids": [c["id"] for c in cases],
        "repeat": args.repeat,
        "max_retries": settings.max_retries,
        "git": _git(),
        "guardrails": {"enabled": guardrails is not None,
                       "sha256": guardrails.sha256 if guardrails else None},
    }
    print_report(meta, summary, runs[-1], checks)

    if not args.no_save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        suffix = f"_x{args.repeat}" if args.repeat > 1 else ""
        guard_tag = "_noguard" if guardrails is None else ""
        path = RESULTS_DIR / f"{stamp}_{provider_name}-{args.model}_{prompt_version}_{args.split}{suffix}{guard_tag}.json"
        payload = {"meta": meta, "summary": summary, "thresholds": checks,
                   "runs": [{"metrics": m, "cases": c} for m, c in zip(runs, run_cases)]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nResultado: {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
