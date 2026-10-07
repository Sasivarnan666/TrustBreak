"""Behaviour Baseline 2.0 tests: deterministic synthetic history, baseline metrics and the new signals."""

import unittest
from datetime import datetime, timedelta

from app.services.behaviour import BehaviourInput, BehaviourProfile, analyze_behaviour, analyze_incident_behaviour
from app.services.behaviour.activity import generate_activity
from app.services.behaviour.baseline import amount_percentile, compute_baseline, max_burst, percentile
from app.services.behaviour.workhours import IST, parse_timestamp, parse_working_hours
from app.services.identity import get_identity

WEEKDAY_NOON = "2026-10-07T12:00:00+05:30"  # Wednesday
CEO = get_identity("CEO-001")
CFO = get_identity("CFO-001")


def ceo(**kw):
    return analyze_incident_behaviour("Arvind Rao", sender_identity_id="CEO-001", **{"channel": "Email", "amount": 50_000, "beneficiary": "Vendor A", **kw})


def codes(r):
    return {a["code"] for a in r["anomalies"]}


class ActivityTests(unittest.TestCase):
    def test_deterministic_and_stable(self):
        generate_activity.cache_clear()
        first = generate_activity(CEO)
        generate_activity.cache_clear()
        self.assertEqual(first, generate_activity(CEO))

    def test_size_and_fields(self):
        for ident in (CEO, CFO):
            events = generate_activity(ident)
            self.assertTrue(50 <= len(events) <= 100)
            e = events[0]
            self.assertEqual(set(e.to_dict()), {"activity_id", "identity_id", "timestamp", "channel", "amount", "currency", "beneficiary", "action", "status"})
            self.assertEqual(len({x.activity_id for x in events}), len(events))

    def test_consistent_with_registry(self):
        hours = parse_working_hours(CEO.typical_working_hours)
        for e in generate_activity(CEO):
            self.assertIn(e.channel, CEO.normal_channels)
            self.assertIn(e.beneficiary, CEO.known_beneficiaries)
            self.assertTrue(CEO.typical_amount_min <= e.amount <= CEO.typical_amount_max)
            t = parse_timestamp(e.timestamp)
            self.assertTrue(hours.contains_time(t) and hours.contains_day(t))

    def test_no_burst_in_history(self):
        times = sorted(parse_timestamp(e.timestamp) for e in generate_activity(CEO))
        self.assertEqual(max_burst(times), 1)


class BaselineMetricTests(unittest.TestCase):
    def test_metrics(self):
        b = compute_baseline(generate_activity(CEO))
        self.assertTrue(b["sufficient"])
        self.assertEqual(b["label"], "Synthetic behavioural baseline")
        self.assertLessEqual(b["amount"]["max"], 200_000)
        self.assertLessEqual(b["amount"]["min"], b["amount"]["median"])
        self.assertAlmostEqual(sum(v["share"] for v in b["channels"].values()), 1.0, places=2)
        self.assertEqual(set(b["channels"]), {"email", "erp"})

    def test_percentile_helper(self):
        self.assertEqual(percentile([1, 2, 3, 4], 50), 2)
        self.assertIsNone(percentile([], 50))

    def test_percentile_label_not_overclaimed(self):
        small = amount_percentile(list(range(1, 88)), 10_000)
        self.assertTrue(small["above_all_history"])
        self.assertNotIn("99th", small["label"])  # 87 events cannot support a >99th claim
        big = amount_percentile(list(range(1, 101)), 10_000)
        self.assertEqual(big["label"], ">99th percentile")


class AcceptanceTests(unittest.TestCase):
    """CEO-001 / Arvind Rao: results must emerge from the baseline engine."""

    def setUp(self):
        self.r = ceo(channel="WhatsApp", amount=1_850_000, beneficiary="Vendor X", timestamp=WEEKDAY_NOON)

    def test_detected_deviations(self):
        self.assertEqual(codes(self.r), {"AMOUNT_ABOVE_BASELINE", "UNUSUAL_CHANNEL", "NEW_BENEFICIARY"})

    def test_amount_evidence(self):
        amt = self.r["checks"]["amount"]
        self.assertEqual(amt["ratio_to_typical_max"], 9.25)
        self.assertEqual(amt["typical_max"], 200_000)
        self.assertTrue(amt["percentile"]["above_all_history"])
        self.assertEqual(self.r["amount_deviation"], 8.25)  # legacy field unchanged

    def test_channel_and_beneficiary_evidence(self):
        ch = next(a for a in self.r["anomalies"] if a["code"] == "UNUSUAL_CHANNEL")
        self.assertTrue(ch["evidence"]["absent_from_history"])
        self.assertNotIn("whatsapp", ch["evidence"]["historical_distribution"])
        ben = next(a for a in self.r["anomalies"] if a["code"] == "NEW_BENEFICIARY")
        self.assertEqual(ben["evidence"]["known_beneficiaries"], ["Vendor A", "Vendor B", "Vendor C"])
        self.assertTrue(all(a["source"] == "synthetic_baseline" for a in self.r["anomalies"]))

    def test_no_double_count_of_channel(self):
        self.assertNotIn("CHANNEL_DISTRIBUTION_ANOMALY", codes(self.r))
        self.assertEqual(self.r["checks"]["channel_distribution"]["status"], "absent_from_history")

    def test_benign_request_has_no_signals(self):
        r = ceo(channel="ERP", amount=150_000, beneficiary="Vendor A", timestamp=WEEKDAY_NOON, recent_request_times=())
        self.assertEqual(r["anomalies"], [])
        self.assertEqual(r["baseline_status"], "SYNTHETIC_BASELINE_AVAILABLE")


class TimeTests(unittest.TestCase):
    def test_unknown_timestamp_never_anomalous(self):
        r = ceo()
        self.assertEqual(r["checks"]["time"]["status"], "not_evaluated")
        self.assertFalse(codes(r) & {"UNUSUAL_TIME", "UNUSUAL_DAY"})

    def test_night_and_sunday(self):
        r = ceo(timestamp="2026-10-04T02:30:00+05:30")  # Sunday 02:30 IST
        self.assertTrue({"UNUSUAL_TIME", "UNUSUAL_DAY"} <= codes(r))

    def test_utc_converted_to_ist(self):
        # 04:00Z = 09:30 IST Wednesday -> inside 09:00-19:00
        self.assertFalse(codes(ceo(timestamp="2026-10-07T04:00:00Z")) & {"UNUSUAL_TIME", "UNUSUAL_DAY"})

    def test_saturday_is_normal_for_ceo_not_cfo(self):
        sat = "2026-10-03T11:00:00+05:30"
        self.assertNotIn("UNUSUAL_DAY", codes(ceo(timestamp=sat)))
        cfo = analyze_incident_behaviour("Meera Iyer", "Email", 100_000, "Vendor A", sender_identity_id="CFO-001", timestamp=sat)
        self.assertIn("UNUSUAL_DAY", codes(cfo))

    def test_parser(self):
        self.assertIsNone(parse_working_hours("whenever"))
        self.assertIsNone(parse_working_hours(None))


class VelocityFrequencyTests(unittest.TestCase):
    def _times(self, minutes_ago):
        now = parse_timestamp(WEEKDAY_NOON)
        return tuple((now - timedelta(minutes=m)).isoformat() for m in minutes_ago)

    def test_velocity_from_real_prior_requests(self):
        r = ceo(timestamp=WEEKDAY_NOON, recent_request_times=self._times([3, 6]))
        self.assertIn("VELOCITY_ANOMALY", codes(r))
        self.assertEqual(r["checks"]["velocity"]["requests_in_window"], 3)

    def test_two_requests_is_not_velocity(self):
        self.assertNotIn("VELOCITY_ANOMALY", codes(ceo(timestamp=WEEKDAY_NOON, recent_request_times=self._times([3]))))

    def test_requests_outside_window_ignored(self):
        self.assertNotIn("VELOCITY_ANOMALY", codes(ceo(timestamp=WEEKDAY_NOON, recent_request_times=self._times([30, 60, 90]))))

    def test_frequency_above_weekly_max(self):
        b = compute_baseline(generate_activity(CEO))
        n = b["frequency"]["per_week_max"]  # need n+1 requests in 7 days including this one
        r = ceo(timestamp=WEEKDAY_NOON, recent_request_times=self._times([60 * 24 * d for d in range(1, n + 1)]))
        self.assertIn("FREQUENCY_ANOMALY", codes(r))
        self.assertTrue(r["frequency_anomaly"])

    def test_no_history_supplied_is_not_evaluated(self):
        r = ceo(timestamp=WEEKDAY_NOON)
        self.assertEqual(r["checks"]["velocity"]["status"], "not_evaluated")
        self.assertFalse(r["frequency_anomaly"])


class NotEnoughDataTests(unittest.TestCase):
    def test_short_history_reports_not_enough(self):
        profile = BehaviourProfile("X-1", "X", "Tester", ("email",), ("Vendor A",), (1000,), activity=generate_activity(CEO)[:5],
                                   working_hours=CEO.typical_working_hours)
        r = analyze_behaviour(BehaviourInput(channel="Email", amount=500, beneficiary="Vendor A", timestamp=WEEKDAY_NOON, recent_request_times=()), profile)
        for k in ("channel_distribution", "frequency", "velocity"):
            self.assertEqual(r["checks"][k]["status"], "NOT_ENOUGH_BASELINE_DATA")
        self.assertEqual(r["baseline_status"], "NOT_ENOUGH_BASELINE_DATA")
        self.assertEqual(r["anomalies"], [])
        self.assertNotIn("percentile", r["checks"]["amount"])

    def test_no_profile(self):
        r = analyze_behaviour(BehaviourInput(), None)
        self.assertEqual(r["baseline_status"], "NOT_ENOUGH_BASELINE_DATA")


class RareChannelTests(unittest.TestCase):
    def test_cfo_phone_rare_or_usual_follows_data(self):
        b = compute_baseline(generate_activity(CFO))
        share = b["channels"]["phone call"]["share"]
        r = analyze_incident_behaviour("Meera Iyer", "Phone call", 100_000, "Vendor A", sender_identity_id="CFO-001", timestamp=WEEKDAY_NOON)
        self.assertEqual("CHANNEL_DISTRIBUTION_ANOMALY" in codes(r), share < 0.10)


if __name__ == "__main__":
    unittest.main()
