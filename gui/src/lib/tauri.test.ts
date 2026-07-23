import { describe, expect, it } from "vitest";
import { buildPairingPayload, type PairingInfo } from "./tauri";

function info(overrides: Partial<PairingInfo>): PairingInfo {
  return {
    enabled: true, host: null, port: 7070, secret: "s3cr3t", lan_secret: "ls3cr3t",
    key: "", lan_ip: undefined, ...overrides,
  };
}

describe("buildPairingPayload", () => {
  // v4 (contract §11.4, LAN-17): the QR carries `lan_secret` (LAN plane), NOT the GUI `secret`; phone
  // rejects v1/v2/v3. Must match phone parsePairingPayload.
  it("prefers lan_ip over host and emits lan_secret, not secret", () => {
    const payload = buildPairingPayload(info({ host: "example.host", lan_ip: "192.168.1.42", key: "K1==" }), "desktop-abc");
    expect(JSON.parse(payload)).toEqual({ v: 4, host: "192.168.1.42", port: 7070, key: "K1==", lan_secret: "ls3cr3t", device: "desktop-abc" });
  });

  it("falls back to host when lan_ip is undefined", () => {
    const payload = buildPairingPayload(info({ host: "example.host", lan_ip: undefined, key: "K2==" }), "desktop-abc");
    expect(JSON.parse(payload)).toEqual({ v: 4, host: "example.host", port: 7070, key: "K2==", lan_secret: "ls3cr3t", device: "desktop-abc" });
  });

  it("falls back to empty string when both lan_ip and host are missing", () => {
    const payload = buildPairingPayload(info({ host: null, lan_ip: undefined, key: "K3==" }), "desktop-abc");
    expect(JSON.parse(payload)).toEqual({ v: 4, host: "", port: 7070, key: "K3==", lan_secret: "ls3cr3t", device: "desktop-abc" });
  });

  it("builds a v4 LAN payload with key + lan_ip host + device, and never leaks the GUI secret", () => {
    const p = JSON.parse(buildPairingPayload({
      enabled: true, host: "", lan_ip: "192.168.1.42",
      port: 7071, secret: "GUI-SECRET", lan_secret: "LS3CRET", key: "BASE64KEY==",
    } as PairingInfo, "desktop-xyz"));
    expect(p).toEqual({ v: 4, host: "192.168.1.42", port: 7071, key: "BASE64KEY==", lan_secret: "LS3CRET", device: "desktop-xyz" });
    expect(p.secret).toBeUndefined();
  });
});
