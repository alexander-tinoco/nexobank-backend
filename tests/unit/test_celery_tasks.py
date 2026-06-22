"""Tests unitarios para los tasks de Celery (sin BD real, sin broker real)."""


def test_evaluate_transaction_risk_placeholder() -> None:
    """El task de riesgo aprueba todo mientras es placeholder."""
    from app.workers.risk_tasks import evaluate_transaction_risk_task

    result = evaluate_transaction_risk_task.run(
        transaction_id="test-id",
        user_id="user-id",
        amount="100.00",
        from_account_id="acc-1",
        to_account_id="acc-2",
        metadata={},
    )
    assert result["approved"] is True
    assert result["risk_score"] == 0.0


def test_generate_monthly_statement_returns_status() -> None:
    """El task de estado de cuenta retorna status=queued con el período correcto."""
    from app.workers.cleanup_tasks import generate_monthly_statement_task

    result = generate_monthly_statement_task.run(
        user_id="user-id",
        account_id="acc-id",
        year=2026,
        month=6,
    )
    assert result["status"] == "queued"
    assert result["period"] == "2026-06"
    assert result["user_id"] == "user-id"


def test_send_login_alert_does_not_raise() -> None:
    """El task de alerta de login no levanta excepción con datos válidos."""
    from app.workers.notification_tasks import send_login_alert_task

    # Debe ejecutarse sin excepción
    send_login_alert_task.run(
        user_id="user-id",
        ip_address="192.168.1.1",
        timestamp="2026-06-22T10:00:00Z",
    )


def test_evaluate_risk_returns_empty_flags() -> None:
    """El task de riesgo retorna lista de flags vacía en el placeholder."""
    from app.workers.risk_tasks import evaluate_transaction_risk_task

    result = evaluate_transaction_risk_task.run(
        transaction_id="tx-abc",
        user_id="user-xyz",
        amount="9999.99",
        from_account_id="acc-from",
        to_account_id="acc-to",
        metadata={"channel": "mobile"},
    )
    assert result["flags"] == []
