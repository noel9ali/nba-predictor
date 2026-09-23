import math
import random

import numpy as np
import torch
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.utils.validation import check_array, check_is_fitted
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


class _LSTMNetwork(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, dropout):
        super().__init__()
        effective_dropout = dropout if num_layers > 1 else 0.0
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=effective_dropout,
        )
        self.output = nn.Linear(hidden_size, 1)

    def forward(self, inputs):
        sequence_output, _ = self.lstm(inputs)
        final_hidden = sequence_output[:, -1, :]
        return self.output(final_hidden).squeeze(1)


class TorchLSTMClassifier(ClassifierMixin, BaseEstimator):
    _estimator_type = "classifier"

    def __init__(
        self,
        hidden_size=32,
        num_layers=1,
        dropout=0.0,
        lr=0.001,
        batch_size=64,
        epochs=15,
        weight_decay=0.0,
        random_state=42,
        device="cpu",
        verbose=0,
    ):
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.lr = lr
        self.batch_size = batch_size
        self.epochs = epochs
        self.weight_decay = weight_decay
        self.random_state = random_state
        self.device = device
        self.verbose = verbose

    def _resolve_device(self):
        if self.device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return self.device

    def _set_random_state(self):
        random.seed(self.random_state)
        np.random.seed(self.random_state)
        torch.manual_seed(self.random_state)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(self.random_state)

    def _build_model(self, input_size):
        network = _LSTMNetwork(
            input_size=input_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )
        return network.to(self.device_)

    def fit(self, X, y):
        X = check_array(X, ensure_2d=True, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32)

        self.n_features_in_ = X.shape[1]
        self.classes_ = np.array([0, 1], dtype=np.int64)
        self.device_ = self._resolve_device()
        self._set_random_state()
        self.model_ = self._build_model(self.n_features_in_)

        inputs = torch.tensor(X, dtype=torch.float32).unsqueeze(1)
        targets = torch.tensor(y, dtype=torch.float32)
        dataset = TensorDataset(inputs, targets)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam(
            self.model_.parameters(),
            lr=self.lr,
            weight_decay=self.weight_decay,
        )

        self.model_.train()
        for epoch in range(self.epochs):
            epoch_loss = 0.0
            for batch_inputs, batch_targets in loader:
                batch_inputs = batch_inputs.to(self.device_)
                batch_targets = batch_targets.to(self.device_)

                optimizer.zero_grad()
                logits = self.model_(batch_inputs)
                loss = criterion(logits, batch_targets)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item() * batch_inputs.size(0)

            if self.verbose:
                average_loss = epoch_loss / len(dataset)
                print(f"LSTM epoch {epoch + 1}/{self.epochs} loss={average_loss:.4f}")

        self.model_.eval()
        self.training_loss_ = epoch_loss / len(dataset)
        self.feature_importances_ = self._compute_feature_importances()
        return self

    def _compute_feature_importances(self):
        check_is_fitted(self, "model_")
        weights = self.model_.lstm.weight_ih_l0.detach().cpu().numpy()
        weights = weights.reshape(4, self.hidden_size, self.n_features_in_)
        importances = np.mean(np.abs(weights), axis=(0, 1))
        total = importances.sum()
        if math.isclose(total, 0.0):
            return np.zeros_like(importances)
        return importances / total

    def predict_proba(self, X):
        check_is_fitted(self, "model_")
        X = check_array(X, ensure_2d=True, dtype=np.float32)

        inputs = torch.tensor(X, dtype=torch.float32).unsqueeze(1).to(self.device_)
        self.model_.eval()
        with torch.no_grad():
            logits = self.model_(inputs)
            probs = torch.sigmoid(logits).detach().cpu().numpy()

        probs = np.clip(probs, 1e-6, 1 - 1e-6)
        return np.column_stack([1.0 - probs, probs])

    def predict(self, X):
        probs = self.predict_proba(X)[:, 1]
        return (probs >= 0.5).astype(int)

    def __getstate__(self):
        state = self.__dict__.copy()
        if "model_" in state and state["model_"] is not None:
            state["_saved_state_dict"] = {
                key: value.detach().cpu()
                for key, value in state["model_"].state_dict().items()
            }
        state["model_"] = None
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        saved_state = self.__dict__.get("_saved_state_dict")
        if saved_state is not None and self.__dict__.get("n_features_in_") is not None:
            self.device_ = self._resolve_device()
            self.model_ = self._build_model(self.n_features_in_)
            self.model_.load_state_dict(saved_state)
            self.model_.eval()
