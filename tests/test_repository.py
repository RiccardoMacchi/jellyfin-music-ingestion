from backend.database.models import DownloadRecord, DownloadStatus


def make_record(**overrides) -> DownloadRecord:
    base = dict(youtube_id="abc123", url="https://youtu.be/abc123", title="Song", artist="Artist")
    base.update(overrides)
    return DownloadRecord(**base)


def test_create_and_get(download_repo):
    created = download_repo.create(make_record())
    assert created.id is not None

    fetched = download_repo.get(created.id)
    assert fetched.youtube_id == "abc123"
    assert fetched.status == DownloadStatus.PENDING.value


def test_find_by_youtube_id_dedupe_level_1(download_repo):
    download_repo.create(make_record(youtube_id="dup1"))
    found = download_repo.find_by_youtube_id("dup1")
    assert found is not None

    not_found = download_repo.find_by_youtube_id("does-not-exist")
    assert not_found is None


def test_find_by_youtube_id_ignores_failed_and_cancelled(download_repo):
    rec = download_repo.create(make_record(youtube_id="dup2"))
    download_repo.update_status(rec.id, DownloadStatus.FAILED, error="boom")
    assert download_repo.find_by_youtube_id("dup2") is None  # puo' essere ritentato


def test_find_by_metadata_dedupe_level_4(download_repo):
    rec = download_repo.create(make_record(
        youtube_id="v1", album="Album X", track_number=3,
    ))
    download_repo.update_status(rec.id, DownloadStatus.COMPLETED)

    found = download_repo.find_by_metadata("Artist", "Album X", "Song", 3)
    assert found is not None
    assert found.id == rec.id


def test_find_by_file_path(download_repo):
    rec = download_repo.create(make_record(youtube_id="v2"))
    download_repo.set_file_path(rec.id, "/music/Artist/Singles/Song.m4a")
    download_repo.update_status(rec.id, DownloadStatus.COMPLETED)

    found = download_repo.find_by_file_path("/music/Artist/Singles/Song.m4a")
    assert found is not None


def test_update_progress(download_repo):
    rec = download_repo.create(make_record())
    download_repo.update_progress(rec.id, 42.5, speed="1.2MiB/s", eta="00:10")

    updated = download_repo.get(rec.id)
    assert updated.progress == 42.5
    assert updated.speed == "1.2MiB/s"
    assert updated.eta == "00:10"


def test_increment_retry(download_repo):
    rec = download_repo.create(make_record())
    download_repo.increment_retry(rec.id)
    download_repo.increment_retry(rec.id)
    assert download_repo.get(rec.id).retry_count == 2


def test_next_pending_returns_oldest_first(download_repo):
    first = download_repo.create(make_record(youtube_id="p1"))
    download_repo.create(make_record(youtube_id="p2"))

    nxt = download_repo.next_pending()
    assert nxt.id == first.id


def test_recover_stuck_jobs_resets_in_flight_statuses(download_repo):
    rec1 = download_repo.create(make_record(youtube_id="r1"))
    download_repo.update_status(rec1.id, DownloadStatus.DOWNLOADING)
    rec2 = download_repo.create(make_record(youtube_id="r2"))
    download_repo.update_status(rec2.id, DownloadStatus.PROCESSING)
    rec3 = download_repo.create(make_record(youtube_id="r3"))
    download_repo.update_status(rec3.id, DownloadStatus.COMPLETED)

    recovered_count = download_repo.recover_stuck_jobs()

    assert recovered_count == 2
    assert download_repo.get(rec1.id).status == DownloadStatus.PENDING.value
    assert download_repo.get(rec2.id).status == DownloadStatus.PENDING.value
    assert download_repo.get(rec3.id).status == DownloadStatus.COMPLETED.value  # non toccato


def test_list_filters_by_status(download_repo):
    r1 = download_repo.create(make_record(youtube_id="l1"))
    download_repo.update_status(r1.id, DownloadStatus.COMPLETED)
    download_repo.create(make_record(youtube_id="l2"))  # resta PENDING

    completed = download_repo.list(status=DownloadStatus.COMPLETED.value)
    assert len(completed) == 1
    assert completed[0].youtube_id == "l1"


def test_delete_removes_record(download_repo):
    rec = download_repo.create(make_record())
    download_repo.delete(rec.id)
    assert download_repo.get(rec.id) is None
