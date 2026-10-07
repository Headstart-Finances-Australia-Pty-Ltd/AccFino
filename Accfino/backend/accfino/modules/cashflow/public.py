"""Public surface of the Cash Flow module: the ONLY import path other modules may use."""
from accfino.modules.cashflow.pipeline import (  # noqa: F401
    auto_detect_columns, preprocess, validate_date_span, monthly_features, train_leaderboard, predict_next_month,
    LEADERBOARD_CSV, NEXT_MONTH_CSV, LEADERBOARD_PLOT, NEXT_MONTH_PLOT,
)
