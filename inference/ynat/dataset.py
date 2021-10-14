from torch.utils.data import Dataset


class YnatDataset(Dataset):

    label2idx = {"정치": 0, "경제": 1, "사회": 2, "생활문화": 3, "세계": 4, "IT과학": 5, "스포츠": 6}

    def __init__(self, data):
        self.data = data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        this_data = self.data[index]
        text = this_data["title"]
        label = this_data["label"]
        label_idx = self.label2idx[label]
        return text, label_idx
