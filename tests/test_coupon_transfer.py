"""Run with: python -m unittest discover -s tests -p test_coupon_transfer.py"""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "admin" / "web"))

from fastapi.testclient import TestClient
from backend import main
from backend.auth import create_session_token
from backend.config import SESSION_COOKIE_NAME
from client.web.backend import main as client_main


class CouponTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "test.db"
        with self.session() as conn:
            main.create_schema(conn)
            conn.executemany(
                "INSERT INTO customers (wid, phone) VALUES (?, ?)",
                [("source", "13800000001"), ("target", "13800000002")],
            )
            conn.executemany(
                """INSERT INTO customer_vehicles (id, customer_wid, vin, plate_no, is_primary)
                   VALUES (?, ?, ?, 'TEST123', 1)""",
                [("source-car", "source", "LEGACY-VIN"), ("target-car", "target", "LEGACY-VIN")],
            )
            for code, status in [("move-me", "unused"), ("keep-me", "unused"), ("voided", "voided")]:
                conn.execute(
                    """INSERT INTO coupons
                       (code, customer_wid, vehicle_id, phone, vin_snapshot, template_name,
                        status, source, valid_end, valid_period, usable_store_names, remark)
                       VALUES (?, 'source', 'source-car', '13800000001', 'LEGACY-VIN',
                               'Maintenance', ?, 'manual', '2099-12-31', '2099-12-31', 'Store A', 'Original')""",
                    (code, status),
                )
            for role in ("admin", "super_admin", "issuer", "redeemer", "record_viewer"):
                conn.execute(
                    "INSERT INTO admin_users (id, username, role, enabled, created_at) VALUES (?, ?, ?, 1, '2026-01-01')",
                    (role, role, role),
                )
            conn.execute(
                """INSERT INTO wechat_bindings (openid, customer_wid, phone, bound_at)
                   VALUES ('verified-target', 'target', '13800000002', '2026-01-01')""",
            )
        self.addCleanup(patch.stopall)
        patch.object(main, "db_session", self.session).start()
        patch.object(client_main, "db_session", self.session).start()
        self.api = TestClient(main.app)
        self.addCleanup(self.api.close)
        self.login("admin")
        self.payload = {"code": "move-me", "source_customer_wid": "source", "target_phone": "13800000002"}
        self.commit = {**self.payload, "target_customer_wid": "target", "target_vehicle_id": "target-car", "remark": "Phone change"}

    @contextmanager
    def session(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def login(self, role):
        self.api.cookies.set(SESSION_COOKIE_NAME, create_session_token(role))

    def post(self, path="transfer", body=None):
        return self.api.post("/api/coupons/" + path, json=body if body is not None else self.commit)

    def coupon(self):
        with self.session() as conn:
            return dict(conn.execute("SELECT * FROM coupons WHERE code = 'move-me'").fetchone())

    def test_transfer_preserves_coupon_and_changes_real_client_visibility(self):
        before = self.coupon()
        preview = self.post("transfer-preview", self.payload)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["target_vehicle"]["id"], "target-car")
        self.assertEqual(self.coupon(), before, "Preview must not mutate records")
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        after = self.coupon()
        expected = {**before, "customer_wid": "target", "phone": "13800000002", "vehicle_id": "target-car"}
        self.assertEqual(after, expected)
        client = TestClient(client_main.app)
        self.addCleanup(client.close)
        for wid, vehicle, expected_codes in [
            ("source", "source-car", {"keep-me"}), ("target", "target-car", {"move-me"}),
        ]:
            client.cookies.set(client_main.SESSION_COOKIE_NAME, wid)
            result = client.get("/api/client/coupons", params={"vehicle_id": vehicle})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual({row["code"] for row in result.json()["items"]}, expected_codes)
        with self.session() as conn:
            log = dict(conn.execute("SELECT * FROM operation_logs WHERE action = '优惠券转移'").fetchone())
            self.assertEqual(log["operator"], "admin")
            self.assertEqual(json.loads(log["remark"])["target_vehicle"]["id"], "target-car")
            self.assertEqual(conn.execute("SELECT customer_wid FROM customer_vehicles WHERE id='source-car'").fetchone()[0], "source")
            self.assertEqual(conn.execute("SELECT phone FROM wechat_bindings WHERE openid='verified-target'").fetchone()[0], "13800000002")
        self.assertEqual(self.post().status_code, 409, "Repeated transfer must not succeed")

    def test_roles_and_anonymous_cannot_transfer(self):
        for role in ("issuer", "redeemer", "record_viewer"):
            self.login(role)
            for path, body in [("transfer-preview", self.payload), ("transfer", self.commit)]:
                self.assertEqual(self.post(path, body).status_code, 403)
        self.api.cookies.clear()
        self.assertEqual(self.post().status_code, 401)
        self.login("super_admin")
        self.assertEqual(self.post("transfer-preview", self.payload).status_code, 200)

    def test_unusable_coupons_are_rejected(self):
        for status, valid_end in [("used", "2099-12-31"), ("voided", "2099-12-31"), ("unused", "2000-01-01")]:
            with self.session() as conn:
                conn.execute("UPDATE coupons SET status=?, valid_end=? WHERE code='move-me'", (status, valid_end))
            self.assertEqual(self.post().status_code, 400)
            self.assertEqual(self.coupon()["customer_wid"], "source")

    def test_status_is_rechecked_after_preview(self):
        self.assertEqual(self.post("transfer-preview", self.payload).status_code, 200)
        with self.session() as conn:
            conn.execute("UPDATE coupons SET status='used', used_time='2026-01-01' WHERE code='move-me'")
        self.assertEqual(self.post().status_code, 400)

    def test_wrong_source_and_stale_destination_are_rejected(self):
        self.assertEqual(self.post(body={**self.commit, "source_customer_wid": "wrong"}).status_code, 409)
        self.assertEqual(self.post(body={**self.commit, "target_vehicle_id": "wrong"}).status_code, 409)
        self.assertEqual(self.post(body={**self.commit, "target_customer_wid": "wrong"}).status_code, 409)
        self.assertEqual(self.post(body={**self.commit, "remark": " "}).status_code, 400)
        self.assertEqual(self.coupon()["customer_wid"], "source")

    def test_same_plate_with_conflicting_valid_vins_is_rejected(self):
        with self.session() as conn:
            conn.execute("UPDATE customer_vehicles SET vin='L1234567890123456' WHERE id='source-car'")
            conn.execute("UPDATE customer_vehicles SET vin='L1234567890123457' WHERE id='target-car'")
        self.assertEqual(self.post().status_code, 400)

    def test_legacy_vin_can_match_same_plate_with_corrected_vin(self):
        with self.session() as conn:
            conn.execute("UPDATE customer_vehicles SET vin='L1234567890123456' WHERE id='target-car'")
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.coupon()["vin_snapshot"], "LEGACY-VIN")

    def test_valid_coupon_snapshot_prevents_transfer_to_different_vin(self):
        with self.session() as conn:
            conn.execute("UPDATE coupons SET vin_snapshot='L1234567890123456' WHERE code='move-me'")
            conn.execute("UPDATE customer_vehicles SET vin='L1234567890123457' WHERE id='target-car'")
        self.assertEqual(self.post().status_code, 400)

    def test_same_vin_with_changed_plate_can_transfer(self):
        with self.session() as conn:
            conn.execute("UPDATE customer_vehicles SET plate_no='NEW123' WHERE id='target-car'")
        self.assertEqual(self.post().status_code, 200)

    def test_duplicate_target_phone_is_not_selected_arbitrarily(self):
        with self.session() as conn:
            conn.execute("INSERT INTO customers (wid, phone) VALUES ('duplicate-account', '13800000002')")
        self.assertEqual(self.post().status_code, 400)

    def test_ambiguous_target_vehicle_is_rejected(self):
        with self.session() as conn:
            conn.execute("INSERT INTO customer_vehicles (id, customer_wid, plate_no) VALUES ('duplicate', 'target', 'TEST123')")
        self.assertEqual(self.post().status_code, 400)

    def test_missing_or_deleted_target_is_rejected(self):
        self.assertEqual(self.post(body={**self.commit, "target_phone": "13800000003"}).status_code, 400)
        with self.session() as conn:
            conn.execute("UPDATE customers SET deleted_at='2026-01-01' WHERE wid='target'")
        self.assertEqual(self.post().status_code, 400)

    def test_audit_failure_rolls_back_transfer(self):
        with self.session() as conn:
            conn.execute("""CREATE TRIGGER reject_audit BEFORE INSERT ON operation_logs
                            BEGIN SELECT RAISE(ABORT, 'test audit failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.post()
        self.assertEqual(self.coupon()["customer_wid"], "source")


if __name__ == "__main__":
    unittest.main()
