# GitHub Copilot'a bağlama (VS Code)

## 1. Organizasyon ayarı (bir kez, org admin)

Copilot Business/Enterprise kullanılıyorsa GitHub organizasyonunda
**Settings → Copilot → Policies → "MCP servers in Copilot"** seçeneği **Enabled** olmalı.
Kapalıysa VS Code'da sunucu görünür ama araçlar kullanılamaz.

## 2. Ekip üyesi kurulumu

Projeye `.vscode/mcp.json` ekleyin (örnek: [`examples/.vscode/mcp.json`](../examples/.vscode/mcp.json)) ya da
komut paletinden **MCP: Add Server → HTTP** ile kullanıcı ayarına ekleyin:

```json
{
  "servers": {
    "models-catalog": { "type": "http", "url": "https://models-mcp.corp.example/mcp" }
  }
}
```

Copilot Chat'i **Agent** moduna alın, araç listesinden `models-catalog` araçlarının açık olduğunu görün.
Sunucu kimlik doğrulaması istemez; erişim ağ seviyesinde sınırlıdır.

## 3. Ne sorulabilir?

| Soru | Çalışan araç |
|---|---|
| "ATG dev'de hangi embedding modelleri var?" | `list_models` |
| "qwen modeli hangi ortamlarda ve hangi adreslerde?" | `get_model` / `search_models` |
| "bge-m3'e UAT'ta cmd ile nasıl istek atarım?" | `get_usage_guide` (shell: cmd) |
| "Prod reranker'a erişmek için hangi portlara yetki lazım?" | `get_access_requirements` |
| "qwen dev ayakta mı?" | `check_health` |
| "Bu modeli kim ne zaman değiştirdi?" | `get_audit_log` |

Hazır akışlar sohbette `/` ile görünür: **`/mcp.models-catalog.add-model`**, **`use-model`**,
**`troubleshoot-access`** (VS Code'da prompt adı sunucu adıyla öne ekli görünür).

## 4. Model ekleme

`/add-model` yazın (isterseniz adresi de verin). Copilot sırayla şunları yapar:

1. Alan listesini ve zorunlulukları okur.
2. Adres verildiyse sunucu erişebiliyorsa model adı, `max_model_len`, motor sürümü gibi alanları adresten önerir.
3. Eksik zorunlu alanları size **tek tek/gruplar halinde sorar** (hiçbirini tahmin etmez).
4. Duplicate kontrolü yapar, özet gösterir, **onayınızı** alır ve kaydeder. `performed_by` için adınızı sorar.

Zorunlu alanlar platforma ve tipe göre değişir:

| Koşul | Ek zorunlu alanlar |
|---|---|
| Her kayıt | model adı, tip, API stili, lokasyon, ortam, platform, base URL, port, gerekli portlar |
| Platform `argocd_k8s` | `k8s_namespace`, `argocd_app` |
| Platform `dev_gpu` / `vm` | `hostname` (modelin hangi makinede olduğu) |
| LLM / vision | `max_model_len` |
| Embedding | `embedding_dim` |
| Özel (custom) servis | `endpoint_path`, `request_example` |

### Duplicate kuralları

| Durum | Sonuç |
|---|---|
| Aynı ad + aynı adres | **Engellenir**; mevcut kayıt gösterilir, `update_deployment` önerilir |
| Aynı adreste farklı ad | Uyarı; kullanıcı onaylarsa eklenir |
| Aynı ad farklı adres | Serbest (replica olabilir; aynı ortamdaysa bilgi notu) |
| Daha önce silinmiş aynı ad+adres | `restore_deployment` önerilir |

Adresler karşılaştırılmadan önce normalize edilir: büyük/küçük harf, sondaki `/` ve `/v1` yok sayılır.

## 5. Silme

Silme **soft delete**'tir (geri alınabilir) ve neden zorunludur. Copilot önce kaydı gösterip açık onay ister;
`confirm=true` olmadan hiçbir şey silinmez. Her işlem `audit_log`'a kim/ne zaman/ne değişti olarak yazılır.

## 6. Yönetici: yapılandırma

Ortam değişkenleri (`CATALOG_` öneki):

| Değişken | Açıklama |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/db` |
| `ALLOWED_HOSTS` | Sunucunun host adı(ları), virgülle. **Üretimde mutlaka doldurun** (DNS-rebinding koruması). `*` = kapalı |
| `PROBE_REACHABLE_LOCATIONS` / `PROBE_REACHABLE_ENVIRONMENTS` | Sunucunun ağ olarak ulaşabildiği yerler (örn. `atg` / `dev,uat`). Boşsa canlı test yoktur, kullanıcıya komut verilir |
| `PROBE_TIMEOUT_SECONDS` | Canlı test zaman aşımı (varsayılan 5) |

Canlı test (`check_health`, `probe_and_autofill`) sunucudan adrese `GET` atar. SSRF'e karşı: yalnızca sabit yollar
(`health_path`, `/v1/models`, `/version`, `/info`), yönlendirme yok, link-local/metadata adresleri engelli, cevabın
yalnızca beyaz listedeki alanları döner.

## 7. Güvenlik notları

- **Kimlik doğrulama yok**: ağa erişebilen herkes okuyabilir **ve yazabilir**. `performed_by` / `X-Performed-By`
  doğrulanmaz, sadece denetim kaydı içindir. Gerekirse kişisel token ya da Entra ID girişi eklenebilir
  (tek giriş noktası: `services/identity.py`).
- Sunucuyu yalnızca şirket içi ağda yayınlayın ve `ALLOWED_HOSTS` değerini ayarlayın.
- Katalogda secret tutulmaz; modellerde auth olmadığından API key alanı yoktur.

## 8. Sorun giderme

| Belirti | Çözüm |
|---|---|
| Araçlar görünmüyor | Org policy "MCP servers in Copilot" kapalı olabilir; Agent modunda olduğunuzdan emin olun |
| `421 Invalid Host header` | İstemcinin kullandığı host adı `CATALOG_ALLOWED_HOSTS` içinde yok |
| `needs_input` dönüyor | Beklenen davranış: eksik alanları Copilot size sorar |
| `check_health` "erişemiyor" diyor | Sunucu o ağda değil; Copilot'un verdiği `run_yourself` komutlarını kendi makinenizde çalıştırın |
