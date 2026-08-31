from pathlib import Path
from runpy import run_path

SCRIPT = run_path(str(Path(__file__).parents[1] / "scripts" / "port_archives.py"))
item_id = SCRIPT["item_id"]
matching_urls = SCRIPT["matching_urls"]
read_archive_ids = SCRIPT["read_archive_ids"]
write_urls = SCRIPT["write_urls"]


def test_read_archive_ids_accepts_both_old_formats(tmp_path):
    yt_dlp_archive = tmp_path / "yt-dlp.txt"
    gallery_dl_archive = tmp_path / "gallery-dl.txt"
    yt_dlp_archive.write_text("tiktok 123\ntiktok 456\n", encoding="utf-8")
    gallery_dl_archive.write_text("456\n789\n", encoding="utf-8")

    assert read_archive_ids((yt_dlp_archive, gallery_dl_archive)) == {
        "123",
        "456",
        "789",
    }


def test_matching_urls_accepts_video_and_photo_paths():
    urls = [
        "https://www.tiktok.com/@a/video/123",
        "https://www.tiktok.com/@b/photo/456?x=1",
        "https://www.tiktok.com/@c/video/789",
        "https://www.tiktok.com/@a/video/123",
    ]

    assert matching_urls(urls, {"123", "456"}) == urls[:2]
    assert item_id("https://example.com/123") is None


def test_write_urls_replaces_the_cache(tmp_path):
    cache = tmp_path / "cache" / "collection.txt"
    write_urls(cache, ["first", "second"])
    write_urls(cache, ["third"])
    assert cache.read_text(encoding="utf-8") == "third\n"
