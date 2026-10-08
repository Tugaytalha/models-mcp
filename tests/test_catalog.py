import pytest

from models_catalog.services import catalog
from models_catalog.services.errors import CatalogError
from models_catalog.services.validation import validate_draft


def _add(session, draft, **kw):
    out = catalog.add(session, draft, actor="tugay", source="mcp", **kw)
    session.commit()
    return out


def _missing(res):
    return {m["field"] for m in res["validation"]["missing_fields"]}


def test_add_complete_llm(session, llm_draft):
    out = _add(session, llm_draft)
    assert out["status"] == "created"
    dep = out["deployment"]
    assert dep["model_id"] == dep["model_name"]
    assert dep["health_path"] == "/health"
    assert dep["status"] == "active"


def test_missing_fields_reported_with_questions(session):
    out = _add(session, {"model_name": "bge-m3", "service_type": "embedding"})
    assert out["status"] == "needs_input"
    missing = {m["field"]: m for m in out["validation"]["missing_fields"]}
    assert {"api_style", "location", "environment", "platform", "base_url", "embedding_dim"} <= set(missing)
    assert missing["location"]["allowed_values"] == ["banka", "atg"]
    assert missing["location"]["question_to_ask"]
    assert "max_model_len" not in missing  # embedding için zorunlu değil


@pytest.mark.parametrize("platform, expected", [
    ("argocd_k8s", {"argocd_app"}),
    ("dev_gpu", {"hostname"}),
    ("vm", {"hostname"}),
])
def test_platform_conditional_required(session, llm_draft, platform, expected):
    llm_draft.pop("k8s_namespace"), llm_draft.pop("argocd_app")
    llm_draft["platform"] = platform
    res = validate_draft(session, llm_draft)
    missing = {m["field"] for m in res.missing_fields}
    assert expected <= missing
    assert "k8s_namespace" not in missing  # namespace hiçbir platformda zorunlu değil


def test_custom_service_requires_endpoint_and_example(session, llm_draft):
    llm_draft.update(service_type="custom", api_style="custom")
    llm_draft.pop("max_model_len")
    res = validate_draft(session, llm_draft)
    assert {"endpoint_path", "request_example"} <= {m["field"] for m in res.missing_fields}
    assert "max_model_len" not in {m["field"] for m in res.missing_fields}


def test_invalid_enum_lists_allowed_values(session, llm_draft):
    llm_draft["environment"] = "staging"
    res = validate_draft(session, llm_draft)
    assert any("geçersiz değer" in e and "dev, uat, prod" in e for e in res.errors)


def test_enum_case_is_normalized(session, llm_draft):
    llm_draft.update(location="ATG", environment="DEV")
    res = validate_draft(session, llm_draft)
    assert res.normalized["location"] == "atg" and res.normalized["environment"] == "dev"


def test_port_autofilled_from_url(session, llm_draft):
    llm_draft.pop("port")
    llm_draft["base_url"] = "http://h:9001"
    res = validate_draft(session, llm_draft)
    assert res.normalized["port"] == 9001 and res.autofilled["port"] == 9001


def test_exact_duplicate_blocked_even_with_url_variants(session, llm_draft):
    _add(session, llm_draft)
    dup = dict(llm_draft, base_url="HTTP://qwen.dev.atg.local:8000/v1/", model_name="Qwen2.5-32B-Instruct")
    out = _add(session, dup)
    assert out["status"] == "blocked"
    assert out["validation"]["duplicates"][0]["kind"] == "exact"


def test_same_name_other_url_allowed_with_info(session, llm_draft):
    _add(session, llm_draft)
    other = dict(llm_draft, base_url="http://qwen2.dev.atg.local:8000")
    out = _add(session, other)
    assert out["status"] == "created"
    assert any(i["code"] == "possible_replica" for i in out["validation"]["infos"])


def test_same_name_other_environment_no_replica_info(session, llm_draft):
    _add(session, llm_draft)
    out = _add(session, dict(llm_draft, environment="uat", base_url="http://qwen.uat.atg.local:8000"))
    assert out["status"] == "created"
    assert out["validation"]["infos"] == []


def test_same_url_other_name_needs_confirmation(session, llm_draft):
    _add(session, llm_draft)
    other = dict(llm_draft, model_name="llama-3-70b")
    out = _add(session, other)
    assert out["status"] == "needs_confirmation"
    assert out["validation"]["warnings"][0]["code"] == "same_url_other_name"
    out = _add(session, other, confirm_warnings=True)
    assert out["status"] == "created"


def test_soft_deleted_suggests_restore(session, llm_draft):
    first = _add(session, llm_draft)["deployment"]
    catalog.soft_delete(session, first["id"], reason="test", actor="tugay", source="mcp")
    session.commit()
    out = _add(session, llm_draft)
    assert out["status"] == "needs_confirmation"
    assert out["validation"]["warnings"][0]["code"] == "restore_candidate"
    assert out["validation"]["duplicates"][0]["kind"] == "soft_deleted"


def test_restore_and_clash(session, llm_draft):
    first = _add(session, llm_draft)["deployment"]
    catalog.soft_delete(session, first["id"], reason="r", actor="a", source="mcp")
    session.commit()
    assert catalog.restore(session, first["id"], actor="a", source="mcp")["status"] == "restored"
    session.commit()
    with pytest.raises(CatalogError):
        catalog.restore(session, first["id"], actor="a", source="mcp")  # silinmiş değil


def test_restore_blocked_when_active_clone_exists(session, llm_draft):
    first = _add(session, llm_draft)["deployment"]
    catalog.soft_delete(session, first["id"], reason="r", actor="a", source="mcp")
    session.commit()
    _add(session, llm_draft, confirm_warnings=True)
    with pytest.raises(CatalogError, match="Geri getirilemiyor"):
        catalog.restore(session, first["id"], actor="a", source="mcp")


def test_consistency_warnings(session, llm_draft):
    llm_draft.update(environment="prod", base_url="http://h:9000", port=8000, required_ports=[443])
    res = validate_draft(session, llm_draft)
    codes = {w.code for w in res.warnings}
    assert {"port_mismatch", "prod_without_owner", "port_not_in_required"} <= codes


def test_actor_required(session, llm_draft):
    with pytest.raises(CatalogError, match="performed_by"):
        catalog.add(session, llm_draft, actor="  ", source="mcp")


def test_update_rechecks_duplicates_and_audits(session, llm_draft):
    a = _add(session, llm_draft)["deployment"]
    b = _add(session, dict(llm_draft, base_url="http://other:8000"))["deployment"]
    out = catalog.update(session, b["id"], {"base_url": "http://qwen.dev.atg.local:8000/v1"},
                         actor="x", source="mcp")
    assert out["status"] == "blocked"
    out = catalog.update(session, a["id"], {"max_model_len": 65536, "owner_team": "ml"},
                         actor="x", source="mcp")
    session.commit()
    assert out["status"] == "updated"
    log = catalog.audit_log(session, deployment_id=a["id"])
    assert [e["action"] for e in log] == ["update", "create"]
    assert set(log[0]["changed_fields"]) >= {"max_model_len", "owner_team"}


def test_update_unrelated_field_ignores_accepted_same_url_duplicate(session, llm_draft):
    """Aynı adreste iki model onaylanıp eklendiyse, alakasız bir alanı güncellemek yeniden onay istememeli."""
    a = _add(session, llm_draft)["deployment"]
    _add(session, dict(llm_draft, model_name="baska"), confirm_warnings=True)
    out = catalog.update(session, a["id"], {"owner_team": "ml"}, actor="x", source="mcp")
    assert out["status"] == "updated"
    # ama adres/ad değişirse kontrol yine çalışır
    out = catalog.update(session, a["id"], {"model_name": "baska"}, actor="x", source="mcp")
    assert out["status"] == "blocked"


def test_update_to_missing_required_is_needs_input(session, llm_draft):
    a = _add(session, llm_draft)["deployment"]
    out = catalog.update(session, a["id"], {"max_model_len": None}, actor="x", source="mcp")
    assert out["status"] == "needs_input"
    assert "max_model_len" in _missing(out)


def test_delete_requires_reason_and_hides_from_list(session, llm_draft):
    a = _add(session, llm_draft)["deployment"]
    with pytest.raises(CatalogError):
        catalog.soft_delete(session, a["id"], reason=" ", actor="x", source="mcp")
    catalog.soft_delete(session, a["id"], reason="kaldırıldı", actor="x", source="mcp")
    session.commit()
    assert catalog.list_deployments(session) == []
    assert len(catalog.list_deployments(session, include_deleted=True)) == 1
    with pytest.raises(CatalogError):
        catalog.update(session, a["id"], {"owner_team": "x"}, actor="x", source="mcp")


def test_search_and_find(session, llm_draft):
    _add(session, dict(llm_draft, tags=["chat", "tr"], description="Türkçe sohbet modeli"))
    assert len(catalog.search(session, "qwen")) == 1
    assert len(catalog.search(session, "sohbet")) == 1
    assert len(catalog.search(session, "tr chat")) == 1
    assert catalog.search(session, "yok-boyle-model") == []
    assert len(catalog.find_by_name(session, "QWEN2.5-32B-INSTRUCT", location="atg", environment="dev")) == 1
    assert catalog.find_by_name(session, "qwen2.5-32b-instruct", environment="prod") == []
