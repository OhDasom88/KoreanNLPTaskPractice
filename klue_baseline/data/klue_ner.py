import argparse
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import List, Optional

import torch
from overrides import overrides
from torch.utils.data import TensorDataset
from transformers import PreTrainedTokenizer

from klue_baseline.data.base import DataProcessor, InputExample, InputFeatures, KlueDataModule
from klue_baseline.data.utils import check_tokenizer_type, convert_examples_to_features

from tqdm import tqdm # 20211014

logger = logging.getLogger(__name__)


class KlueNERProcessor(DataProcessor):

    # origin_train_file_name = "klue-ner-v1.1_train.tsv"#default
    # origin_dev_file_name = "klue-ner-v1.1_dev.tsv"#default
    # origin_test_file_name = "klue-ner-v1.1_test.tsv"#default
    origin_train_file_name = "21101316_bio_train.tsv"# 211014
    origin_dev_file_name = "21101316_bio_val.tsv"# 211014
    origin_test_file_name = "21101316_bio_test.tsv"# 211014

    datamodule_type = KlueDataModule

    def __init__(self, args: argparse.Namespace, tokenizer: PreTrainedTokenizer) -> None:
        super().__init__(args, tokenizer)
        self.tokenizer_type = check_tokenizer_type(tokenizer)  # One of the ["xlm-sp", "bert-wp", "other']

    @overrides
    def get_train_dataset(self, data_dir: str, file_name: Optional[str] = None) -> TensorDataset:
        file_path = os.path.join(data_dir, file_name or self.origin_train_file_name)

        logger.info(f"Loading from {file_path}")
        return self._create_dataset(file_path, "train")

    @overrides
    def get_dev_dataset(self, data_dir: str, file_name: Optional[str] = None) -> TensorDataset:
        file_path = os.path.join(data_dir, file_name or self.origin_dev_file_name)

        logger.info(f"Loading from {file_path}")
        return self._create_dataset(file_path, "valid")

    @overrides
    def get_test_dataset(self, data_dir: str, file_name: Optional[str] = None) -> TensorDataset:
        file_path = os.path.join(data_dir, file_name or self.origin_test_file_name)

        if not os.path.exists(file_path):
            logger.info("Test dataset doesn't exists. So loading dev dataset instead.")
            file_path = os.path.join(data_dir, self.hparams.dev_file_name or self.origin_dev_file_name)

        logger.info(f"Loading from {file_path}")
        return self._create_dataset(file_path, "test")

    @overrides
    def get_labels(self) -> List[str]:
        # return ["B-PS", "I-PS", "B-LC", "I-LC", "B-OG", "I-OG", "B-DT", "I-DT", "B-TI", "I-TI", "B-QT", "I-QT", "O"]
        return ["B-INGR", "I-INGR", "B-QTY", "I-QTY", "B-UNIT", "I-UNIT", "O"]# 211014

    def _is_punctuation(char: str) -> bool:
        """Checks whether `chars` is a punctuation character."""
        cp = ord(char)
        # We treat all non-letter/number ASCII as punctuation.
        # Characters such as "^", "$", and "`" are not in the Unicode
        # Punctuation class but we treat them as punctuation anyways, for
        # consistency.
        if (cp >= 33 and cp <= 47) or (cp >= 58 and cp <= 64) or (cp >= 91 and cp <= 96) or (cp >= 123 and cp <= 126):
            return True
        cat = unicodedata.category(char)
        if cat.startswith("P"):
            return True
        return False

    def _create_examples(self, file_path: str, dataset_type: str) -> List[InputExample]:
        """Loads the raw dataset and converts to InputExample.

        Since the ner dataset is tagged in character-level, subword-level token
        label should be aligned with the given unit. Here, we take the first
        character label for the token label.
        """
        is_training = dataset_type == "train"
        if self.tokenizer_type == "xlm-sp":
            strip_char = "???"
        elif self.tokenizer_type == "bert-wp":
            strip_char = "##"
        else:
            raise ValueError("This code only supports XLMRobertaTokenizer & BertWordpieceTokenizer")

        examples = []
        ori_examples = []
        file_path = Path(file_path)
        raw_text = file_path.read_text().strip()
        # raw_docs = re.split(r"\n\t?\n", raw_text)# default
        raw_docs = re.split(r"[\n][#]{2}[\w]+[\n]", raw_text)# 211014 recipe
        cnt = 0
        for doc in tqdm(raw_docs):
            original_clean_tokens = []  # clean tokens (bert clean func)
            original_clean_labels = []  # clean labels (bert clean func)
            sentence = ""
            for line in doc.split("\n"):
                if line[:2] == "##":
                    guid = line.split("\t")[0].replace("##", "")
                    continue
                elif len(line.split("\t")) !=2: continue # 20211014 
                token, tag = line.split("\t")
                sentence += token
                if token == " ":
                    continue
                original_clean_tokens.append(token)
                original_clean_labels.append(tag)
            # sentence: "?????? ?????????.."
            # original_clean_labels: [???, ???, ???, ???, ???, ., .]
            sent_words = sentence.split(" ")
            # sent_words: [??????, ?????????..]
            modi_labels = []
            char_idx = 0
            for word in sent_words:
                # ??????, ?????????
                correct_syllable_num = len(word)
                tokenized_word = self.tokenizer.tokenize(word)
                # case1: ?????? tokenizer --> [???, ##???]
                # case2: wp tokenizer --> [??????]
                # case3: ??????, wp tokenizer?????? unk --> [unk]
                # unk?????? --> ????????? ????????? unk??? ??????, ???, ????????? ??????
                contain_unk = True if self.tokenizer.unk_token in tokenized_word else False
                for i, token in enumerate(tokenized_word):
                    token = token.replace(strip_char, "")
                    if not token:
                        modi_labels.append("O")
                        continue
                    modi_labels.append(original_clean_labels[char_idx])
                    if not contain_unk:
                        char_idx += len(token)
                if contain_unk:
                    char_idx += correct_syllable_num

            text_a = sentence  # original sentence
            examples.append(InputExample(guid=guid, text_a=text_a, label=modi_labels))
            ori_examples.append({"original_sentence": text_a, "original_clean_labels": original_clean_labels})
            cnt += 1
        if not is_training:
            data = getattr(self.hparams, "data", {})
            data[dataset_type] = {"original_examples": ori_examples}
            setattr(self.hparams, "data", data)
            setattr(self.hparams, "tokenizer", self.tokenizer)
        return examples

    def _convert_features(self, examples: List[InputExample]) -> List[InputFeatures]:
        return convert_examples_to_features(
            examples,
            self.tokenizer,
            label_list=self.get_labels(),
            max_length=self.hparams.max_seq_length,
            task_mode="tagging",
        )

    def _create_dataset(self, file_path: str, dataset_type: str) -> TensorDataset:
        examples = self._create_examples(file_path, dataset_type)
        features = self._convert_features(examples)

        all_input_ids = torch.tensor([f.input_ids for f in features], dtype=torch.long)
        all_attention_mask = torch.tensor([f.attention_mask for f in features], dtype=torch.long)
        # Some model does not make use of token type ids (e.g. RoBERTa)
        all_token_type_ids = torch.tensor(
            [0 if f.token_type_ids is None else f.token_type_ids for f in features], dtype=torch.long
        )
        all_labels = torch.tensor([f.label for f in features], dtype=torch.long)

        return TensorDataset(all_input_ids, all_attention_mask, all_token_type_ids, all_labels)

    @staticmethod
    def add_specific_args(parser: argparse.ArgumentParser, root_dir: str) -> argparse.ArgumentParser:
        parser = KlueDataModule.add_specific_args(parser, root_dir)
        parser.add_argument(
            "--max_seq_length",
            # default=128,
            default=510,
            type=int,
            help="The maximum total input sequence length after tokenization. Sequences longer "
            "than this will be truncated, sequences shorter will be padded.",
        )
        return parser
