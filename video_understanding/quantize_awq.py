from __future__ import annotations

import argparse


def parse_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quantize a dense Qwen VL checkpoint with AutoAWQ.")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--w-bit", type=int, default=4)
    parser.add_argument("--q-group-size", type=int, default=128)
    parser.add_argument("--zero-point", type=parse_bool, default=True)
    parser.add_argument("--version", default="GEMM")
    args = parser.parse_args(argv)

    try:
        from awq import AutoAWQForCausalLM
        from transformers import AutoProcessor, AutoTokenizer
    except ImportError as exc:
        raise SystemExit(
            "AutoAWQ and transformers are required. Install with the quant extra first."
        ) from exc

    quant_config = {
        "zero_point": args.zero_point,
        "q_group_size": args.q_group_size,
        "w_bit": args.w_bit,
        "version": args.version,
    }
    model = AutoAWQForCausalLM.from_pretrained(args.model_path, trust_remote_code=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    model.quantize(tokenizer, quant_config=quant_config)
    model.save_quantized(args.output_path)
    tokenizer.save_pretrained(args.output_path)
    try:
        processor = AutoProcessor.from_pretrained(args.model_path, trust_remote_code=True)
        processor.save_pretrained(args.output_path)
    except Exception as exc:  # noqa: BLE001
        print(f"warning: quantized model saved, but processor save failed: {exc}")
    print(args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
