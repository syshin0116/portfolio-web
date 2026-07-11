"""Tests for stable user-specific persistence identities."""

import pytest

from api.resource_scope import scoped_checkpoint_thread_id
from db import _scope_namespace, _unscope_namespace


def test_checkpoint_identity_is_stable_and_owner_scoped():
    public_thread_id = "11111111-1111-4111-8111-111111111111"

    alice = scoped_checkpoint_thread_id("alice", public_thread_id)
    bob = scoped_checkpoint_thread_id("bob", public_thread_id)

    assert alice == scoped_checkpoint_thread_id("alice", public_thread_id)
    assert alice != bob
    assert alice != public_thread_id


def test_store_namespace_round_trips_only_for_owner():
    public_namespace = ["memories", "preferences"]
    alice = _scope_namespace("alice", public_namespace)
    bob = _scope_namespace("bob", public_namespace)

    assert alice != bob
    assert _unscope_namespace("alice", alice) == public_namespace
    with pytest.raises(ValueError, match="does not belong"):
        _unscope_namespace("bob", alice)
