import argparse
import json
import random
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

from project_config import BASE_DIR, CHAT_DATASET
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)


DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_DATASET = CHAT_DATASET
DEFAULT_OUTPUT = BASE_DIR / "trained_qwen2.5_3b_lora"


def load_records(dataset_path, max_samples, seed):
    records = []
    with open(dataset_path, encoding="utf-8") as dataset_file:
        for line in dataset_file:
            record = json.loads(line)
            messages = record.get("messages", [])
            if len(messages) >= 2 and messages[-1].get("role") == "assistant":
                records.append(messages)

    if not records:
        raise ValueError(f"No assistant chat examples found in {dataset_path}.")

    if max_samples is not None and max_samples < len(records):
        random.Random(seed).shuffle(records)
        records = records[:max_samples]
    return records


def encode_records(records, tokenizer, max_length):
    encoded = []
    for messages in records:
        prompt_ids = tokenizer.apply_chat_template(
            messages[:-1], tokenize=True, add_generation_prompt=True
        )
        input_ids = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False
        )
        if input_ids[:len(prompt_ids)] != prompt_ids:
            raise ValueError("Chat template prompt is not a prefix of the full example.")

        trim = max(0, len(input_ids) - max_length)
        input_ids = input_ids[trim:]
        prompt_length = max(0, len(prompt_ids) - trim)
        labels = [-100] * min(prompt_length, len(input_ids))
        labels.extend(input_ids[len(labels):])
        if any(label != -100 for label in labels):
            encoded.append({"input_ids": input_ids, "labels": labels})

    if not encoded:
        raise ValueError("No assistant response tokens remain after tokenization.")
    return encoded


class ChatDataCollator:
    def __init__(self, pad_token_id):
        self.pad_token_id = pad_token_id

    def __call__(self, features):
        max_length = max(len(feature["input_ids"]) for feature in features)
        input_ids = []
        labels = []
        attention_mask = []
        for feature in features:
            padding = max_length - len(feature["input_ids"])
            input_ids.append(feature["input_ids"] + [self.pad_token_id] * padding)
            labels.append(feature["labels"] + [-100] * padding)
            attention_mask.append([1] * len(feature["input_ids"]) + [0] * padding)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
        }


def parse_args():
    parser = argparse.ArgumentParser(description="QLoRA fine-tuning for Al-Majarrat chat data")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--max-length", type=int, default=384)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--save-steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main():
    args = parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable. Install CUDA-enabled PyTorch before training.")

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"Loading {args.model} in 4-bit NF4; output is a LoRA adapter, not a merged model.")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quantization_config,
        torch_dtype=torch.float16,
        device_map={"": 0},
        low_cpu_mem_usage=True,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(
        model,
        LoraConfig(
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        ),
    )
    model.print_trainable_parameters()

    records = load_records(dataset_path, args.max_samples, args.seed)
    train_dataset = encode_records(records, tokenizer, args.max_length)
    print(f"Training examples: {len(train_dataset):,}; max sequence length: {args.max_length}")

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        fp16=True,
        gradient_checkpointing=True,
        optim="adamw_torch",
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        max_grad_norm=0.3,
        logging_steps=1,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=2,
        dataloader_num_workers=0,
        remove_unused_columns=False,
        report_to="none",
        seed=args.seed,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=ChatDataCollator(tokenizer.pad_token_id),
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    Path(args.output_dir, "NOTICE.txt").write_text(
        "Improved using Qwen. Base model: Qwen/Qwen2.5-3B-Instruct. "
        "Use and distribution are subject to the Qwen Research License Agreement.\n",
        encoding="utf-8",
    )
    print(f"LoRA adapter saved to {args.output_dir}")


if __name__ == "__main__":
    main()