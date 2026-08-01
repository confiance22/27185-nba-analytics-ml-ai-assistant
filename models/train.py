"""
models/train.py

Trains Logistic Regression and Random Forest on the feature dataset,
evaluates on a held-out test set, performs a depth-sweep overfitting
check, and persists both models.

Day 7: fit both classifiers on the feature set, evaluated on a test
split, and saved the trained models to saved_models/.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from models.features import build_features
from etl.logging_setup import get_logger

logger = get_logger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_models")


def load_and_split():
    df = build_features()
    X = df.drop(columns=["game_id", "home_win"])
    y = df["home_win"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logger.info(f"Train: {len(X_train)} rows, Test: {len(X_test)} rows")
    return X_train, X_test, y_train, y_test


def print_confusion_matrix(y_true, y_pred):
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    print(f"  {'':>15} {'Predicted 0':>12} {'Predicted 1':>12}")
    print(f"  {'Actual 0':>15} {tn:>12} {fp:>12}")
    print(f"  {'Actual 1':>15} {fn:>12} {tp:>12}")


def evaluate_model(model, X_train, y_train, X_test, y_test, name):
    logger.info(f"Training {name}...")
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")
    print(f"  Accuracy:  {acc:.4f}")
    print(f"\n  Classification report:")
    print(classification_report(y_test, y_pred, target_names=["Visitor win", "Home win"]))
    print(f"  Confusion matrix:")
    print_confusion_matrix(y_test, y_pred)
    return acc, model


def depth_sweep(X_train, y_train, X_test, y_test):
    print(f"\n{'=' * 70}")
    print("  Random Forest — depth sweep (overfitting check)")
    print(f"{'=' * 70}")
    for depth in [2, 6, None]:
        label = str(depth) if depth is not None else "None (unconstrained)"
        rf = RandomForestClassifier(n_estimators=200, max_depth=depth, random_state=42)
        rf.fit(X_train, y_train)
        train_acc = accuracy_score(y_train, rf.predict(X_train))
        test_acc = accuracy_score(y_test, rf.predict(X_test))
        gap = train_acc - test_acc
        flag = " <-- POSSIBLE OVERFIT" if gap > 0.15 else ""
        print(f"  max_depth={label:>24}:  train={train_acc:.4f}  test={test_acc:.4f}  gap={gap:.4f}{flag}")


def main():
    os.makedirs(MODEL_DIR, exist_ok=True)
    X_train, X_test, y_train, y_test = load_and_split()

    majority_class = y_train.mode()[0]
    acc_baseline = (y_test == majority_class).mean()
    print(f"\n  Baseline (always predict majority class = {majority_class}):")
    print(f"  Accuracy:  {acc_baseline:.4f}")

    lr = LogisticRegression(max_iter=1000, random_state=42)
    acc_lr, lr_model = evaluate_model(lr, X_train, y_train, X_test, y_test, "Logistic Regression")

    rf = RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42)
    acc_rf, rf_model = evaluate_model(rf, X_train, y_train, X_test, y_test, "Random Forest (max_depth=6)")

    depth_sweep(X_train, y_train, X_test, y_test)

    better_model = "Logistic Regression" if acc_lr >= acc_rf else "Random Forest"
    better_acc = max(acc_lr, acc_rf)
    print(f"\n{'=' * 70}")
    print(f"  CONCLUSION: {better_model} ({better_acc:.1%}) beats baseline ({acc_baseline:.1%})")
    print(f"{'=' * 70}")

    joblib.dump(lr_model, os.path.join(MODEL_DIR, "logistic_regression_model.pkl"))
    joblib.dump(rf_model, os.path.join(MODEL_DIR, "random_forest_model.pkl"))
    logger.info(f"Models saved to {MODEL_DIR}")


if __name__ == "__main__":
    main()
