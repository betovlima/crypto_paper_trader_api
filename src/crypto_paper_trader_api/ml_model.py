from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from xgboost import XGBClassifier

from .indicators import FEATURE_COLUMNS


@dataclass(frozen=True)
class ModelPrediction:
    upward_probability: float
    downward_probability: float
    expected_return: float
    model_signal: str
    accuracy: float | None
    precision: float | None
    recall: float | None
    roc_auc: float | None
    training_rows: int
    top_features_json: str


class XGBoostDirectionModel:
    """Chronological next-candle direction model.

    The target is 1 when the next candle closes above the current candle by more than
    ``direction_threshold``. Trading fees are deliberately excluded from the target so
    the model evaluates market direction rather than exchange economics. The last 20%
    of rows are used as a chronological holdout before the final model is fitted on all
    historical rows.
    """

    def __init__(
        self,
        required_gross_return: float = 0.0,
        buy_threshold: float = 0.55,
        sell_threshold: float = 0.42,
    ):
        # The legacy parameter name is retained for API compatibility. In v0.8.0 it is a
        # pure direction threshold and must not include fees, spread or slippage.
        self.direction_threshold = required_gross_return
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def fit_predict(self, indicator_frame: pd.DataFrame) -> ModelPrediction:
        data = indicator_frame.copy()
        data["forward_return"] = data["close"].shift(-1) / data["close"] - 1
        data["target"] = (data["forward_return"] > self.direction_threshold).astype(int)

        training = data.dropna(subset=[*FEATURE_COLUMNS, "forward_return"]).copy()
        latest = data.dropna(subset=FEATURE_COLUMNS).tail(1)

        if latest.empty or len(training) < 120 or training["target"].nunique() < 2:
            return self._fallback_prediction(data, training)

        split_index = max(int(len(training) * 0.80), 80)
        split_index = min(split_index, len(training) - 20)
        train_part = training.iloc[:split_index]
        test_part = training.iloc[split_index:]

        model = self._new_model()
        model.fit(train_part[FEATURE_COLUMNS], train_part["target"])

        metrics = self._evaluate(model, test_part)

        # Refit using all known, chronologically valid observations.
        model.fit(training[FEATURE_COLUMNS], training["target"])
        probability = float(model.predict_proba(latest[FEATURE_COLUMNS])[0, 1])

        positive_returns = training.loc[training["target"] == 1, "forward_return"]
        negative_returns = training.loc[training["target"] == 0, "forward_return"]
        mean_positive = float(positive_returns.mean()) if not positive_returns.empty else 0.0
        mean_negative = float(negative_returns.mean()) if not negative_returns.empty else 0.0
        expected_return = probability * mean_positive + (1 - probability) * mean_negative

        feature_importance = sorted(
            zip(FEATURE_COLUMNS, model.feature_importances_, strict=True),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
        top_features_json = json.dumps(
            [
                {"feature": name, "importance": round(float(value), 6)}
                for name, value in feature_importance
            ]
        )

        return ModelPrediction(
            upward_probability=probability,
            downward_probability=1 - probability,
            expected_return=expected_return,
            model_signal=self._signal(probability),
            accuracy=metrics["accuracy"],
            precision=metrics["precision"],
            recall=metrics["recall"],
            roc_auc=metrics["roc_auc"],
            training_rows=len(training),
            top_features_json=top_features_json,
        )

    @staticmethod
    def _new_model() -> XGBClassifier:
        return XGBClassifier(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.04,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_weight=3,
            reg_alpha=0.05,
            reg_lambda=1.0,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            n_jobs=1,
        )

    @staticmethod
    def _evaluate(model: XGBClassifier, test_part: pd.DataFrame) -> dict[str, float | None]:
        if test_part.empty:
            return {"accuracy": None, "precision": None, "recall": None, "roc_auc": None}

        y_true = test_part["target"]
        probabilities = model.predict_proba(test_part[FEATURE_COLUMNS])[:, 1]
        predictions = (probabilities >= 0.5).astype(int)

        roc_auc: float | None = None
        if y_true.nunique() == 2:
            roc_auc = float(roc_auc_score(y_true, probabilities))

        return {
            "accuracy": float(accuracy_score(y_true, predictions)),
            "precision": float(precision_score(y_true, predictions, zero_division=0)),
            "recall": float(recall_score(y_true, predictions, zero_division=0)),
            "roc_auc": roc_auc,
        }

    def _fallback_prediction(self, data: pd.DataFrame, training: pd.DataFrame) -> ModelPrediction:
        """Use a transparent momentum estimate until enough training data exists."""

        latest = data.dropna(subset=["rsi_14", "ema_gap_20_50", "return_3", "adx_14"]).tail(1)
        probability = 0.5
        if not latest.empty:
            row = latest.iloc[0]
            score = 0.0
            score += np.clip(float(row["ema_gap_20_50"]) * 150, -0.15, 0.15)
            score += np.clip(float(row["return_3"]) * 8, -0.12, 0.12)
            score += np.clip((float(row["rsi_14"]) - 50) / 200, -0.10, 0.10)
            if float(row["adx_14"]) < 15:
                score *= 0.6
            probability = float(np.clip(0.5 + score, 0.05, 0.95))

        expected_return = 0.0
        if not training.empty:
            expected_return = float(training["forward_return"].mean())

        return ModelPrediction(
            upward_probability=probability,
            downward_probability=1 - probability,
            expected_return=expected_return,
            model_signal=self._signal(probability),
            accuracy=None,
            precision=None,
            recall=None,
            roc_auc=None,
            training_rows=len(training),
            top_features_json="[]",
        )

    def _signal(self, probability: float) -> str:
        if probability >= self.buy_threshold:
            return "BUY"
        if probability <= self.sell_threshold:
            return "SELL"
        return "HOLD"
