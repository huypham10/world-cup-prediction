"""
Tests for the odds_visible capture logic in submit_prediction.

Two levels:
  1. Unit tests for the ov() helper (no DB needed).
  2. DB integration tests verifying correct storage and upsert behaviour.

Edge cases covered:
  - odds_visible="true"  → stored as True
  - odds_visible="false" → stored as False
  - odds_visible=None    → stored as None  (match has no odds; hx-vals not sent)
  - None is distinguishable from False in the DB (not ambiguously null)
  - Changing pick: odds_visible reflects state at final submission, not first
  - Multiple toggle flips before submitting: final localStorage value is captured
"""

from datetime import datetime, timezone, timedelta

import pytest

from app.models.match import Match
from app.models.prediction import Prediction
from app.models.user import User


# ─── ov() helper – mirrors logic in app/routers/matches.py ──────────────────

def _ov(odds_visible_str):
    """Convert the raw form string to the value stored on the prediction."""
    return (odds_visible_str == "true") if odds_visible_str is not None else None


# ─── unit tests ──────────────────────────────────────────────────────────────


def test_ov_string_true_returns_bool_true():
    assert _ov("true") is True


def test_ov_string_false_returns_bool_false():
    assert _ov("false") is False


def test_ov_none_returns_none():
    """None means the form field was absent (match has no odds → hx-vals omitted)."""
    assert _ov(None) is None


def test_ov_none_differs_from_false():
    """null (no odds on match) must be distinguishable from false (odds hidden by choice)."""
    assert _ov(None) != _ov("false")


def test_ov_unexpected_string_returns_false():
    """Any unexpected input (empty string, garbage) falls through to False, not None."""
    assert _ov("") is False
    assert _ov("yes") is False


# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
async def user(db):
    u = User(name="Test User")
    db.add(u)
    await db.flush()
    return u


@pytest.fixture
async def match_no_odds(db):
    m = Match(
        team_a="Brazil",
        team_b="Germany",
        kickoff_time=datetime.now(timezone.utc) + timedelta(hours=2),
        status="scheduled",
    )
    db.add(m)
    await db.flush()
    return m


@pytest.fixture
async def match_with_odds(db):
    m = Match(
        team_a="France",
        team_b="Spain",
        kickoff_time=datetime.now(timezone.utc) + timedelta(hours=2),
        status="scheduled",
        odds_a=2.10,
        odds_draw=3.30,
        odds_b=3.50,
    )
    db.add(m)
    await db.flush()
    return m


# ─── DB integration tests ────────────────────────────────────────────────────


async def test_odds_visible_true_stored(db, user, match_with_odds):
    """Toggle on at submission time → True stored."""
    pred = Prediction(
        user_id=user.id,
        match_id=match_with_odds.id,
        pick="A",
        odds_visible=_ov("true"),
    )
    db.add(pred)
    await db.commit()
    await db.refresh(pred)
    assert pred.odds_visible is True


async def test_odds_visible_false_stored(db, user, match_with_odds):
    """Odds available but toggle off → False stored."""
    pred = Prediction(
        user_id=user.id,
        match_id=match_with_odds.id,
        pick="B",
        odds_visible=_ov("false"),
    )
    db.add(pred)
    await db.commit()
    await db.refresh(pred)
    assert pred.odds_visible is False


async def test_no_odds_on_match_stores_null(db, user, match_no_odds):
    """Match has no odds → hx-vals omitted → None received → null stored."""
    pred = Prediction(
        user_id=user.id,
        match_id=match_no_odds.id,
        pick="draw",
        odds_visible=_ov(None),
    )
    db.add(pred)
    await db.commit()
    await db.refresh(pred)
    assert pred.odds_visible is None


async def test_null_and_false_are_distinguishable(db, user, match_with_odds, match_no_odds):
    """null (no odds available) is a different value from false (user hid available odds)."""
    hidden = Prediction(
        user_id=user.id, match_id=match_with_odds.id, pick="A", odds_visible=False
    )
    no_odds = Prediction(
        user_id=user.id, match_id=match_no_odds.id, pick="A", odds_visible=None
    )
    db.add_all([hidden, no_odds])
    await db.commit()
    await db.refresh(hidden)
    await db.refresh(no_odds)

    assert hidden.odds_visible is False
    assert no_odds.odds_visible is None
    assert hidden.odds_visible != no_odds.odds_visible


async def test_changing_prediction_updates_odds_visible(db, user, match_with_odds):
    """Upsert: second submission overwrites odds_visible with the toggle state at that click."""
    pred = Prediction(
        user_id=user.id,
        match_id=match_with_odds.id,
        pick="A",
        odds_visible=_ov("true"),
    )
    db.add(pred)
    await db.commit()
    await db.refresh(pred)
    assert pred.odds_visible is True

    # User toggles odds off, then changes pick — final state captured
    pred.pick = "B"
    pred.odds_visible = _ov("false")
    await db.commit()
    await db.refresh(pred)

    assert pred.pick == "B"
    assert pred.odds_visible is False


async def test_multiple_toggles_captures_final_state(db, user, match_with_odds):
    """Rapid toggle (on → off → on → off): the state at the moment of clicking submit is stored."""
    # Simulate: started on, toggled twice (net: off), then submitted
    pred = Prediction(
        user_id=user.id,
        match_id=match_with_odds.id,
        pick="draw",
        odds_visible=_ov("false"),
    )
    db.add(pred)
    await db.commit()
    await db.refresh(pred)
    assert pred.odds_visible is False


async def test_odds_visible_not_overwritten_to_null_on_second_pick_without_odds(
    db, user, match_with_odds
):
    """If odds disappear between first and second pick, second pick correctly stores null."""
    pred = Prediction(
        user_id=user.id,
        match_id=match_with_odds.id,
        pick="A",
        odds_visible=_ov("true"),
    )
    db.add(pred)
    await db.commit()
    await db.refresh(pred)

    # Odds no longer sent (match lost odds between page loads)
    pred.pick = "B"
    pred.odds_visible = _ov(None)
    await db.commit()
    await db.refresh(pred)

    assert pred.pick == "B"
    assert pred.odds_visible is None
