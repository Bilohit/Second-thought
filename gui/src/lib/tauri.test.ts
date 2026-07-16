import { describe, expect, it } from "vitest";
import { buildPairingPayload, type PairingInfo } from "./tauri";

function info(overrides: Partial<PairingInfo>): PairingInfo {
  return {
    enabled: true, host: null, port: 7070, secret: "s3cr3t",
    key: "", lan_ip: undefined, ...overrides,
  };
}

describe("buildPairingPayload", () => {
  // v3 (contract §11.4): device anchor added; phone rejects v1/v2. Must match phone parsePairingPayload.
  it("prefers lan_ip over host", () => {
    const payload = buildPairingPayload(info({ host: "example.host", lan_ip: "192.168.1.42", key: "K1==" }), "desktop-abc");
    expect(JSON.parse(payload)).toEqual({ v: 3, host: "192.168.1.42", port: 7070, key: "K1==", secret: "s3cr3t", device: "desktop-abc" });
  });

  it("falls back to host when lan_ip is undefined", () => {
    const payload = buildPairingPayload(info({ host: "example.host", lan_ip: undefined, key: "K2==" }), "desktop-abc");
    expect(JSON.parse(payload)).toEqual({ v: 3, host: "example.host", port: 7070, key: "K2==", secret: "s3cr3t", device: "desktop-abc" });
  });

  it("falls back to empty string when both lan_ip and host are missing", () => {
    const payload = buildPairingPayload(info({ host: null, lan_ip: undefined, key: "K3==" }), "desktop-abc");
    expect(JSON.parse(payload)).toEqual({ v: 3, host: "", port: 7070, key: "K3==", secret: "s3cr3t", device: "desktop-abc" });
  });

  it("builds a v3 LAN payload with key + lan_ip host + device", () => {
    const p = JSON.parse(buildPairingPayload({
      enabled: true, host: "", lan_ip: "192.168.1.42",
      port: 7071, secret: "S3CRET", key: "BASE64KEY==",
    } as PairingInfo, "desktop-xyz"));
    expect(p).toEqual({ v: 3, host: "192.168.1.42", port: 7071, key: "BASE64KEY==", secret: "S3CRET", device: "desktop-xyz" });
  });
});
