"""
Тесты Config — загрузка, валидация, дефолты, безопасность.

API-ключи НЕ нужны — тестируется логика парсинга.
"""

import json
import os
import pytest
import tempfile

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import (
    Config, TradingConfig, RiskConfig, NotificationsConfig, BotConfig,
    load_config, validate_config,
)


class TestDefaults:
    """Дефолтные значения dataclass-ов."""

    def test_trading_defaults(self):
        tc = TradingConfig()
        assert tc.symbol == "ETHUSDT"
        assert tc.side == "Buy"
        assert tc.leverage == 4
        assert tc.take_profit_pct == 1.0
        assert tc.stop_loss_pct == 5.0
        assert tc.max_entries == 5
        assert tc.entry_step_pct == 2.0
        assert tc.position_size_pct == 5.0
        assert tc.working_deposit == 1000.0

    def test_risk_defaults(self):
        rc = RiskConfig()
        assert rc.max_position_pct_of_balance == 95.0
        assert rc.check_liquidation is True
        assert rc.allow_short is False

    def test_config_defaults(self):
        cfg = Config()
        assert cfg.bybit_testnet is True
        assert cfg.bybit_api_key == ""
        assert isinstance(cfg.trading, TradingConfig)
        assert isinstance(cfg.risk, RiskConfig)


class TestLoadConfig:
    """Тесты load_config()."""

    def test_load_from_json(self, tmp_path):
        """config.json переопределяет дефолты."""
        json_data = {
            "trading": {
                "symbol": "BTCUSDT",
                "leverage": 3,
                "take_profit_pct": 2.0,
                "stop_loss_pct": 5.0,
                "max_entries": 3,
                "entry_step_pct": 1.5,
                "position_size_pct": 10.0,
                "working_deposit": 2000.0,
            }
        }
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps(json_data), encoding="utf-8")

        # Пустой .env чтобы не подхватывать реальный
        env_path = tmp_path / ".env"
        env_path.write_text("", encoding="utf-8")

        cfg = load_config(
            env_path=str(env_path),
            config_path=str(json_path),
        )
        assert cfg.trading.symbol == "BTCUSDT"
        assert cfg.trading.leverage == 3
        assert cfg.trading.take_profit_pct == 2.0

    def test_load_missing_json(self, tmp_path):
        """Без config.json → дефолтные значения."""
        env_path = tmp_path / ".env"
        env_path.write_text("", encoding="utf-8")

        cfg = load_config(
            env_path=str(env_path),
            config_path=str(tmp_path / "nonexistent.json"),
        )
        assert cfg.trading.symbol == "ETHUSDT"
        assert cfg.trading.leverage == 4

    def test_safety_overrides(self, tmp_path):
        """allow_short и side принудительно сбрасываются."""
        json_data = {
            "trading": {
                "side": "Sell",
                "symbol": "ETHUSDT",
                "leverage": 4,
                "take_profit_pct": 1.0,
                "stop_loss_pct": 5.0,
                "max_entries": 5,
                "entry_step_pct": 2.0,
                "position_size_pct": 5.0,
                "working_deposit": 1000.0,
            },
            "risk": {
                "allow_short": True,
                "max_position_pct_of_balance": 95.0,
                "check_liquidation": True,
            },
        }
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps(json_data), encoding="utf-8")
        env_path = tmp_path / ".env"
        env_path.write_text("", encoding="utf-8")

        cfg = load_config(
            env_path=str(env_path),
            config_path=str(json_path),
        )
        # Принудительная безопасность
        assert cfg.risk.allow_short is False
        assert cfg.trading.side == "Buy"


class TestValidateConfig:
    """Тесты validate_config()."""

    def _valid_config(self):
        cfg = Config()
        cfg.bybit_api_key = "real-key"
        cfg.bybit_api_secret = "real-secret"
        cfg.telegram_bot_token = "123456:ABC"
        cfg.telegram_chat_id = "987654"
        return cfg

    def test_valid_config_no_errors(self):
        """Полностью валидная конфигурация → 0 ошибок."""
        errors = validate_config(self._valid_config())
        assert len(errors) == 0

    def test_missing_api_key(self):
        cfg = self._valid_config()
        cfg.bybit_api_key = ""
        errors = validate_config(cfg)
        assert any("BYBIT_API_KEY" in e for e in errors)

    def test_placeholder_secret(self):
        cfg = self._valid_config()
        cfg.bybit_api_secret = "your_api_secret_here"
        errors = validate_config(cfg)
        assert any("BYBIT_API_SECRET" in e for e in errors)

    def test_bad_leverage_zero(self):
        cfg = self._valid_config()
        cfg.trading.leverage = 0
        errors = validate_config(cfg)
        assert any("leverage" in e for e in errors)

    def test_bad_leverage_too_high(self):
        cfg = self._valid_config()
        cfg.trading.leverage = 15
        errors = validate_config(cfg)
        assert any("leverage" in e for e in errors)

    def test_bad_deposit(self):
        cfg = self._valid_config()
        cfg.trading.working_deposit = 50
        errors = validate_config(cfg)
        assert any("working_deposit" in e for e in errors)

    def test_bad_take_profit(self):
        cfg = self._valid_config()
        cfg.trading.take_profit_pct = 0
        errors = validate_config(cfg)
        assert any("take_profit_pct" in e for e in errors)

    def test_short_blocked(self):
        cfg = self._valid_config()
        cfg.risk.allow_short = True
        errors = validate_config(cfg)
        assert any("allow_short" in e for e in errors)
