from app.jobs import job_store

if __name__ == "__main__":
    print(f"Removed {job_store.cleanup_expired()} expired jobs.")
