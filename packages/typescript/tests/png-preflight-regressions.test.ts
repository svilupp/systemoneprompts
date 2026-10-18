import { expect, test } from "bun:test";
import { deflateSync } from "node:zlib";
import { PNG } from "pngjs";
import { TypeSafeClient } from "../src/client.js";
import { imageAsset } from "../src/file-assets.js";

const signature = Buffer.from("89504e470d0a1a0a", "hex");

function chunk(type: string, content: Buffer): Buffer {
  const name = Buffer.from(type);
  const size = Buffer.alloc(4);
  size.writeUInt32BE(content.length);
  let crc = 0xffffffff;
  for (const byte of Buffer.concat([name, content])) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
  return Buffer.concat([size, name, content, checksum]);
}

function header(interlace = 1, color = 6, depth = 8): Buffer {
  const result = Buffer.alloc(13);
  result.writeUInt32BE(300, 0);
  result.writeUInt32BE(300, 4);
  result[8] = depth;
  result[9] = color;
  result[12] = interlace;
  return chunk("IHDR", result);
}

function png(data: Buffer, ihdr: Buffer = header(), beforeData: Buffer = Buffer.alloc(0)): Buffer {
  return Buffer.concat([
    signature,
    ihdr,
    beforeData,
    chunk("IDAT", deflateSync(data)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// The seven Adam7 pass dimensions for a 300 x 300 image, including rounded edge pixels.
const passSizes: [number, number][] = [
  [38, 38],
  [37, 38],
  [75, 37],
  [75, 75],
  [150, 75],
  [150, 150],
  [300, 150],
];

test("ordinary, interlaced, packed, indexed and 16-bit PNGs preserve their wire bytes", async () => {
  const ordinary = PNG.sync.write(new PNG({ width: 300, height: 300 }));
  const valid = [ordinary];
  const formats: [number, number, number][] = [
    [0, 1, 1],
    [2, 8, 3],
    [3, 2, 1],
    [4, 16, 2],
    [6, 16, 4],
  ];
  for (const [color, depth, channels] of formats) {
    const rawSize = passSizes.reduce(
      (size, [columns, rows]) => size + rows * (1 + Math.ceil((columns * channels * depth) / 8)),
      0,
    );
    valid.push(
      png(
        Buffer.alloc(rawSize),
        header(1, color, depth),
        color === 3 ? chunk("PLTE", Buffer.from([0, 0, 0])) : Buffer.alloc(0),
      ),
    );
  }
  let calls = 0;
  const client = new TypeSafeClient({
    apiKey: "test",
    cloudflareAccountId: "",
    baseURL: "https://api.typesafe.ai",
    headers: { "TypeSafe-Danger-Zone-Images": "true" },
    fetch: async (_, init) => {
      expect(JSON.parse(String(init?.body)).assets.photo.data_base64).toBe(
        valid[calls++]!.toString("base64"),
      );
      return Response.json({
        model: "jev",
        answers: { q: { type: "noul", noul: 1 } },
        usage: { input_tokens: 1, output_tokens: 1 },
      });
    },
  });
  for (const bytes of valid) {
    const asset = imageAsset(bytes);
    expect(asset).toEqual({ type: "image", format: "png", data_base64: bytes.toString("base64") });
    await client.systemOne({
      state: "photo",
      questions: { q: { type: "noul" } },
      assets: { photo: asset },
    });
  }
  expect(calls).toBe(valid.length);
});

test("oversized interlaced scanlines fail with bounded memory through imageAsset and native requests", () => {
  // This compresses to about 32 KiB but expands far beyond the declared image's scanlines.
  // Keep the probe at the review's 32 MiB ceiling, isolated from the test runner's allocations.
  const malformed = png(Buffer.alloc(32 * 1024 * 1024));
  const script = `
    import { readFileSync } from "node:fs";
    import { imageAsset } from ${JSON.stringify(new URL("../src/file-assets.ts", import.meta.url).href)};
    import { TypeSafeClient } from ${JSON.stringify(new URL("../src/client.ts", import.meta.url).href)};
    const bytes = readFileSync(0);
    const asset = { type: "image", format: "png", data_base64: bytes.toString("base64") };
    let calls = 0;
    const client = new TypeSafeClient({
      apiKey: "test", cloudflareAccountId: "", baseURL: "https://api.typesafe.ai", maxRetries: 0,
      headers: { "TypeSafe-Danger-Zone-Images": "true" },
      fetch: async () => { calls++; throw new Error("transport called"); },
    });
    const before = process.memoryUsage().external;
    let rejected = 0;
    try { imageAsset(bytes); } catch { rejected++; }
    try { await client.systemOne({ state: "photo", questions: { q: { type: "noul" } }, assets: { photo: asset } }); }
    catch { rejected++; }
    console.log(JSON.stringify({ rejected, calls, externalBytes: process.memoryUsage().external - before }));
  `;
  const child = Bun.spawnSync([process.execPath, "--eval", script], { stdin: malformed });
  expect(child.exitCode).toBe(0);
  const result = JSON.parse(child.stdout.toString());
  expect(result.rejected).toBe(2);
  expect(result.calls).toBe(0);
  // The prior decoder retained about 68 MiB for just one rejection of this same fixture.
  expect(result.externalBytes).toBeLessThan(16 * 1024 * 1024);
});

test("duplicate or invalid headers, truncated chunks, CRC errors and APNG chunks are rejected", () => {
  const ordinary = PNG.sync.write(new PNG({ width: 300, height: 300 }));
  const corrupt = Buffer.from(ordinary);
  corrupt[29] = corrupt[29]! ^ 1; // IHDR CRC, without changing dimensions or payload.
  const raw = Buffer.alloc(300 * (1 + 300 * 4));
  const invalid = [
    Buffer.concat([ordinary.subarray(0, 33), ordinary.subarray(8)]),
    png(raw, header(0, 2, 1)), // RGB cannot use packed 1-bit samples.
    png(raw, header(2)),
    ordinary.subarray(0, -1),
    corrupt,
    ...["acTL", "fcTL", "fdAT"].map((type) => png(raw, header(0), chunk(type, Buffer.alloc(0)))),
    png(raw.subarray(1), header(0)),
    png(Buffer.concat([raw, Buffer.from([0])]), header(0)),
  ];
  for (const bytes of invalid) expect(() => imageAsset(bytes)).toThrow();
});
