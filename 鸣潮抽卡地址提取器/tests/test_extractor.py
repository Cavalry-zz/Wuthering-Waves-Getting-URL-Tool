import tempfile
import unittest
from pathlib import Path

from wuwa_link_extractor import DECODE_TABLE, extract_urls_from_bytes, read_latest_url


URL_1 = (
    "https://aki-gm-resources.aki-game.com/aki/gacha/index.html#/record?"
    "svr_id=1000&player_id=123456789&lang=zh-Hans&gacha_id=1&"
    "gacha_type=1&svr_area=cn&record_id=secret-one&resources_id=1"
)
URL_2 = (
    "https://aki-gm-resources-oversea.aki-game.net/aki/gacha/index.html#/record?"
    "svr_id=2000&player_id=987654321&lang=en&gacha_id=2&"
    "gacha_type=2&svr_area=global&record_id=secret-two&resources_id=2"
)


def encode_for_decode_table(plain: bytes) -> bytes:
    inverse = bytearray(256)
    for encrypted, decoded in enumerate(DECODE_TABLE):
        inverse[decoded] = encrypted
    return plain.translate(bytes(inverse))


class ExtractorTests(unittest.TestCase):
    def test_extracts_plain_cn_url(self):
        urls = extract_urls_from_bytes(f"prefix {URL_1} suffix".encode())
        self.assertIn(URL_1, urls)

    def test_extracts_json_escaped_url(self):
        escaped = URL_2.replace("/", r"\/").replace("&", r"\u0026")
        urls = extract_urls_from_bytes(f'{{"#url":"{escaped}"}}'.encode())
        self.assertIn(URL_2, urls)

    def test_extracts_xor_encoded_url(self):
        raw = encode_for_decode_table(f"noise {URL_1} end".encode())
        urls = extract_urls_from_bytes(raw)
        self.assertIn(URL_1, urls)

    def test_rejects_unrelated_urls(self):
        raw = b"https://example.com/gacha/index.html#/record?player_id=123"
        self.assertEqual([], extract_urls_from_bytes(raw))

    def test_latest_url_wins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log = Path(temp_dir) / "Client.log"
            log.write_bytes((URL_1 + "\n" + URL_2).encode())
            self.assertEqual(URL_2, read_latest_url(log))


if __name__ == "__main__":
    unittest.main()
