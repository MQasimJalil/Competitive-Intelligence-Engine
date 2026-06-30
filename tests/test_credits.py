from app.credits.store import FileCreditStore


def test_file_credit_store_records_grants_and_successful_ai_spend_once(tmp_path):
    store = FileCreditStore(tmp_path)

    grant = store.grant(user_id="user-1", amount=3, reason="beta_grant")
    first_spend = store.spend_successful_ai_report(user_id="user-1", job_id="job-1")
    duplicate_spend = store.spend_successful_ai_report(user_id="user-1", job_id="job-1")

    assert grant.amount == 3
    assert first_spend is not None
    assert first_spend.amount == -1
    assert duplicate_spend is None
    assert store.balance_for_user("user-1") == 2
    assert [entry.reason for entry in store.list_for_user("user-1")] == [
        "beta_grant",
        "successful_ai_report",
    ]


def test_file_credit_store_rejects_spend_without_available_credit(tmp_path):
    store = FileCreditStore(tmp_path)

    result = store.spend_successful_ai_report(user_id="user-1", job_id="job-1")

    assert result is None
    assert store.balance_for_user("user-1") == 0


def test_file_credit_store_thread_safe_spend(tmp_path):
    import concurrent.futures
    store = FileCreditStore(tmp_path)
    store.grant(user_id="user-1", amount=1, reason="initial_grant")

    # Try to spend the credit concurrently using multiple threads for different jobs
    def run_spend(job_id):
        return store.spend_successful_ai_report(user_id="user-1", job_id=job_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_spend, f"job-{i}") for i in range(5)]
        results = [f.result() for f in futures]

    successful_spends = [r for r in results if r is not None]
    assert len(successful_spends) == 1
    assert store.balance_for_user("user-1") == 0

