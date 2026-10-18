import { inflateSync } from "node:zlib";
import jpeg from "jpeg-js";
import { PNG } from "pngjs";
import type { ImageAsset } from "./native.js";

export const MAX_IMAGE_BYTES = 16 * 1024 * 1024;

/** Decode complete image data; dimensions and formats are checked without modifying pixels. */
export function imageAsset(bytes: Uint8Array): ImageAsset {
  const data = Buffer.from(bytes);
  if (!data.length || data.length > MAX_IMAGE_BYTES)
    throw new Error("image must contain 1 byte through 16 MiB");
  let width: number;
  let height: number;
  let format: "png" | "jpg";
  if (data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    preflightPng(data);
    ({ width, height } = PNG.sync.read(data, { checkCRC: true }));
    format = "png";
  } else if (data[0] === 255 && data[1] === 216) {
    if (data[data.length - 2] !== 255 || data[data.length - 1] !== 217)
      throw new Error("truncated JPEG image");
    checkJpegDimensions(data);
    ({ width, height } = jpeg.decode(data, {
      useTArray: true,
      maxResolutionInMP: 3,
      maxMemoryUsageInMB: 64,
      tolerantDecoding: false,
    }));
    format = "jpg";
  } else throw new Error("image must be PNG or JPEG bytes");
  checkDimensions(width, height);
  return { type: "image", format, data_base64: data.toString("base64") };
}

/** pngjs inflates Adam7 images without a cap; admit only a bounded, complete stream first. */
function preflightPng(data: Buffer): void {
  if (data.length < 33) throw new Error("truncated PNG image");
  if (data.readUInt32BE(8) !== 13 || data.toString("latin1", 12, 16) !== "IHDR")
    throw new Error("PNG must begin with one 13-byte IHDR");
  const width = data.readUInt32BE(16);
  const height = data.readUInt32BE(20);
  checkDimensions(width, height);
  const depth = data[24]!;
  const color = data[25]!;
  const channels = [1, 0, 3, 1, 2, 0, 4][color];
  const validDepths = color === 0 ? [1, 2, 4, 8, 16] : color === 3 ? [1, 2, 4, 8] : [8, 16];
  if (
    !channels ||
    !validDepths.includes(depth) ||
    data[26] !== 0 ||
    data[27] !== 0 ||
    data[28]! > 1
  )
    throw new Error("invalid PNG header");

  const idat: Buffer[] = [];
  let ended = false;
  let dataEnded = false;
  let palette = false;
  for (let offset = 33; offset < data.length; ) {
    if (offset + 12 > data.length) throw new Error("truncated PNG image");
    const length = data.readUInt32BE(offset);
    const end = offset + length + 12;
    if (end > data.length) throw new Error("truncated PNG image");
    const type = data.toString("latin1", offset + 4, offset + 8);
    if (!/^[A-Za-z]{2}[A-Z][A-Za-z]$/.test(type)) throw new Error("invalid PNG chunk type");
    if (type === "IHDR") throw new Error("duplicate PNG IHDR");
    if (["acTL", "fcTL", "fdAT"].includes(type)) throw new Error("animated PNG is unsupported");
    if (type === "IDAT") {
      if (dataEnded || (color === 3 && !palette)) throw new Error("invalid PNG chunk order");
      idat.push(data.subarray(offset + 8, end - 4));
    } else {
      if (idat.length) dataEnded = true;
      if (type === "PLTE") {
        if (
          palette ||
          dataEnded ||
          color === 0 ||
          color === 4 ||
          length < 3 ||
          length > 768 ||
          length % 3 ||
          (color === 3 && length / 3 > 2 ** depth)
        )
          throw new Error("invalid PNG palette");
        palette = true;
      }
      if (type === "IEND") {
        if (length !== 0 || end !== data.length || !idat.length) throw new Error("invalid PNG end");
        ended = true;
      }
    }
    offset = end;
  }
  if (!ended) throw new Error("truncated PNG image");

  // Adam7 starting coordinates and strides; each pass has independently padded rows and filters.
  const passes: [number, number, number, number][] =
    data[28] === 0
      ? [[0, 0, 1, 1]]
      : [
          [0, 0, 8, 8],
          [4, 0, 8, 8],
          [0, 4, 4, 8],
          [2, 0, 4, 4],
          [0, 2, 2, 4],
          [1, 0, 2, 2],
          [0, 1, 1, 2],
        ];
  let expectedBytes = 0;
  for (const [x, y, dx, dy] of passes) {
    const columns = Math.max(0, Math.ceil((width - x) / dx));
    const rows = Math.max(0, Math.ceil((height - y) / dy));
    if (columns && rows) expectedBytes += rows * (1 + Math.ceil((columns * channels * depth) / 8));
  }
  if (inflateSync(Buffer.concat(idat), { maxOutputLength: expectedBytes }).length !== expectedBytes)
    throw new Error("invalid PNG scanline length");
}

function checkDimensions(width: number, height: number): void {
  if (width < 280 || height < 280 || width > 1568 || height > 1568)
    throw new Error(`image dimensions ${width}x${height} must each be 280..1568 pixels`);
}

/** Bound JPEG frame dimensions before allocating a decoded pixel buffer. */
function checkJpegDimensions(data: Buffer): void {
  for (let offset = 2; offset + 4 <= data.length; ) {
    if (data[offset++] !== 255) throw new Error("invalid JPEG marker");
    while (data[offset] === 255) offset++;
    const marker = data[offset++]!;
    if (marker === 0xda || marker === 0xd9) break;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    const length = data.readUInt16BE(offset);
    if (length < 2 || offset + length > data.length) throw new Error("truncated JPEG image");
    if ([0xc0, 0xc1, 0xc2].includes(marker)) {
      if (length < 8) throw new Error("invalid JPEG frame");
      checkDimensions(data.readUInt16BE(offset + 5), data.readUInt16BE(offset + 3));
      return;
    }
    offset += length;
  }
  throw new Error("unsupported JPEG frame");
}
