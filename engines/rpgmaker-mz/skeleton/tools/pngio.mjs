// ---------------------------------------------------------------------------
// pngio.mjs
// Purpose : Read and write PNG files and move pixels around, with Node's standard library only (zlib). Used by
//           tools/dotwork_mz.mjs to turn Dotwork's art into RPG Maker MZ's image layouts.
// Usage   : import { readPng, writePng, decodePng, encodePng, blank, crop, blit, scale, stretch, fill } from "./pngio.mjs";
//           const img = readPng("a.png");  writePng("b.png", scale(img, 3));
// Notes   : An image is { width, height, data } with data a Uint8Array of RGBA, 4 bytes per pixel, rows top to bottom.
//           Reads every non-interlaced PNG a paint program or Pillow writes: greyscale, RGB, palette (with tRNS),
//           grey + alpha and RGBA, at 1, 2, 4, 8 or 16 bits (16-bit keeps the high byte). Interlaced (Adam7) files are
//           refused with a message (re-save them without interlacing). Writes 8-bit RGBA with no metadata, so the same
//           pixels always give the same bytes (the converter compares hashes). Pixel art only: every scale is
//           nearest-neighbour.
//
// Pseudocode:
//   decode: check the signature -> walk the chunks (IHDR, PLTE, tRNS, IDAT..., IEND) -> inflate the IDAT data ->
//           undo each row's filter (None, Sub, Up, Average, Paeth) -> expand the samples to RGBA
//   encode: filter every row with Sub or None (whichever is smaller) -> deflate -> IHDR, IDAT, IEND with CRCs
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { readFileSync, writeFileSync } from "node:fs";
import { crc32, deflateSync, inflateSync } from "node:zlib";

const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const CHANNELS = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 };   // colour type -> samples per pixel
const DEPTHS = { 0: [1, 2, 4, 8, 16], 2: [8, 16], 3: [1, 2, 4, 8], 4: [8, 16], 6: [8, 16] };
const MAX_SIDE = 16384;                               // larger images are refused (a damaged header, not art)

/** A PNG problem the caller reports as one line. */
export class PngError extends Error {}

// ---- reading ------------------------------------------------------------------------------------------
/** Decode PNG bytes to { width, height, data } (RGBA). where: a name for messages. */
export function decodePng(bytes, where = "PNG") {
  const buf = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
  if (buf.length < 8 || !buf.subarray(0, 8).equals(SIGNATURE)) throw new PngError(`${where}: not a PNG file`);
  let pos = 8, ihdr = null, palette = null, trns = null, ended = false;
  const idat = [];
  while (pos < buf.length) {
    if (pos + 12 > buf.length) throw new PngError(`${where}: cut short (a chunk header past the end of the file)`);
    const len = buf.readUInt32BE(pos);
    const type = buf.toString("latin1", pos + 4, pos + 8);
    if (pos + 12 + len > buf.length) throw new PngError(`${where}: cut short in its ${type} chunk`);
    const body = buf.subarray(pos + 8, pos + 8 + len);
    if (type === "IHDR") {
      ihdr = { width: body.readUInt32BE(0), height: body.readUInt32BE(4), depth: body[8], colour: body[9], interlace: body[12] };
    } else if (type === "PLTE") palette = body;
    else if (type === "tRNS") trns = body;
    else if (type === "IDAT") idat.push(body);
    else if (type === "IEND") { ended = true; break; }
    pos += 12 + len;
  }
  if (!ihdr) throw new PngError(`${where}: no IHDR chunk`);
  if (!ended) throw new PngError(`${where}: cut short (no IEND chunk)`);
  const { width, height, depth, colour, interlace } = ihdr;
  if (!(colour in CHANNELS) || !DEPTHS[colour].includes(depth)) {
    throw new PngError(`${where}: colour type ${colour} at ${depth} bits is not a valid PNG combination`);
  }
  if (interlace) throw new PngError(`${where}: interlaced PNG; re-save it without interlacing`);
  if (!width || !height || width > MAX_SIDE || height > MAX_SIDE) throw new PngError(`${where}: size ${width}x${height} out of range`);
  if (colour === 3 && !palette) throw new PngError(`${where}: palette image without a PLTE chunk`);
  if (!idat.length) throw new PngError(`${where}: no image data (IDAT)`);
  let raw;
  try {
    raw = inflateSync(Buffer.concat(idat));
  } catch (err) {
    throw new PngError(`${where}: image data does not inflate (${err.message})`);
  }
  const bitsPerPixel = CHANNELS[colour] * depth;
  const stride = Math.ceil((width * bitsPerPixel) / 8);
  const bpp = Math.max(1, bitsPerPixel >> 3);         // the filter's byte distance
  if (raw.length < height * (stride + 1)) throw new PngError(`${where}: image data is shorter than ${width}x${height}`);
  const rows = unfilter(raw, height, stride, bpp, where);
  return { width, height, data: toRgba(rows, width, height, stride, depth, colour, palette, trns) };
}

// Undo the per-row filters in place; returns the filtered-free bytes, rows back to back (stride each)
function unfilter(raw, height, stride, bpp, where) {
  const out = new Uint8Array(height * stride);
  for (let y = 0; y < height; y++) {
    const f = raw[y * (stride + 1)];
    const src = y * (stride + 1) + 1;
    const row = y * stride, up = row - stride;
    for (let i = 0; i < stride; i++) {
      const x = raw[src + i];
      const a = i >= bpp ? out[row + i - bpp] : 0;
      const b = y > 0 ? out[up + i] : 0;
      const c = y > 0 && i >= bpp ? out[up + i - bpp] : 0;
      let v;
      if (f === 0) v = x;
      else if (f === 1) v = x + a;
      else if (f === 2) v = x + b;
      else if (f === 3) v = x + ((a + b) >> 1);
      else if (f === 4) {
        const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        v = x + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c);
      } else throw new PngError(`${where}: unknown row filter ${f} on row ${y}`);
      out[row + i] = v & 255;
    }
  }
  return out;
}

// Expand unfiltered samples of any supported type and depth to RGBA bytes
function toRgba(rows, width, height, stride, depth, colour, palette, trns) {
  const data = new Uint8Array(width * height * 4);
  const ch = CHANNELS[colour];
  const max = (1 << Math.min(depth, 8)) - 1;
  const sample = (row, index) => {                    // the index-th sample of a row, as 0..255 (or a palette index)
    if (depth === 8) return rows[row + index];
    if (depth === 16) return rows[row + index * 2];  // the high byte
    const bit = index * depth;
    const v = (rows[row + (bit >> 3)] >> (8 - depth - (bit & 7))) & max;
    return colour === 3 ? v : Math.round((v * 255) / max);
  };
  // a tRNS key colour, compared at the file's own depth (16-bit keys compare their high byte, as samples do here)
  const key = trns && colour !== 3 ? Array.from({ length: trns.length >> 1 }, (_, i) =>
    depth === 16 ? trns[i * 2] : depth === 8 ? trns[i * 2 + 1] : Math.round((trns.readUInt16BE(i * 2) * 255) / max)) : null;
  for (let y = 0; y < height; y++) {
    const row = y * stride;
    for (let x = 0; x < width; x++) {
      const o = (y * width + x) * 4;
      let r, g, b, a = 255;
      if (colour === 3) {
        const i = sample(row, x);
        r = palette[i * 3] ?? 0; g = palette[i * 3 + 1] ?? 0; b = palette[i * 3 + 2] ?? 0;
        if (trns && i < trns.length) a = trns[i];
      } else if (colour === 0 || colour === 4) {
        r = g = b = sample(row, x * ch);
        if (colour === 4) a = sample(row, x * ch + 1);
        else if (key && r === key[0]) a = 0;
      } else {
        r = sample(row, x * ch); g = sample(row, x * ch + 1); b = sample(row, x * ch + 2);
        if (colour === 6) a = sample(row, x * ch + 3);
        else if (key && r === key[0] && g === key[1] && b === key[2]) a = 0;
      }
      data[o] = r; data[o + 1] = g; data[o + 2] = b; data[o + 3] = a;
    }
  }
  return data;
}

/** Read a PNG file. */
export function readPng(file) {
  return decodePng(readFileSync(file), file);
}

// ---- writing ------------------------------------------------------------------------------------------
function chunk(type, body) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(body.length, 0);
  head.write(type, 4, "latin1");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body])) >>> 0, 0);
  return Buffer.concat([head, body, crc]);
}

/** Encode { width, height, data } as 8-bit RGBA PNG bytes (deterministic: no time or text chunks). */
export function encodePng(img) {
  const { width, height, data } = img;
  const stride = width * 4;
  const raw = Buffer.alloc(height * (stride + 1));
  for (let y = 0; y < height; y++) {
    const row = y * stride, dst = y * (stride + 1);
    // Sub (1) suits flat pixel art; keep None (0) when Sub does not make the row smaller by the usual sum test
    let sumNone = 0, sumSub = 0;
    for (let i = 0; i < stride; i++) {
      const v = data[row + i], s = (v - (i >= 4 ? data[row + i - 4] : 0)) & 255;
      sumNone += v < 128 ? v : 256 - v;
      sumSub += s < 128 ? s : 256 - s;
    }
    const sub = sumSub < sumNone;
    raw[dst] = sub ? 1 : 0;
    for (let i = 0; i < stride; i++) {
      raw[dst + 1 + i] = sub ? (data[row + i] - (i >= 4 ? data[row + i - 4] : 0)) & 255 : data[row + i];
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = 6;                           // 8 bits, RGBA; compression, filter, interlace 0
  return Buffer.concat([SIGNATURE, chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0))]);
}

/** Write an image as PNG. */
export function writePng(file, img) {
  writeFileSync(file, encodePng(img));
}

// ---- pixels -------------------------------------------------------------------------------------------
/** A transparent image (or filled with rgba [r, g, b, a]). */
export function blank(width, height, rgba = null) {
  const img = { width, height, data: new Uint8Array(width * height * 4) };
  if (rgba) fill(img, 0, 0, width, height, rgba);
  return img;
}

/** Set a rectangle to one colour (clipped to the image); rgba [0, 0, 0, 0] clears it. */
export function fill(img, x, y, w, h, rgba) {
  for (let yy = Math.max(0, y); yy < Math.min(img.height, y + h); yy++) {
    for (let xx = Math.max(0, x); xx < Math.min(img.width, x + w); xx++) img.data.set(rgba, (yy * img.width + xx) * 4);
  }
  return img;
}

/** A copy of a rectangle of img (pixels outside img come out transparent). */
export function crop(img, x, y, w, h) {
  const out = blank(w, h);
  blit(out, img, -x, -y);
  return out;
}

/**
 * Draw src onto dst with its top-left at (dx, dy), clipped. over: alpha-blend (src over dst) instead of copying,
 * so a transparent source pixel keeps what is under it.
 */
export function blit(dst, src, dx, dy, over = false) {
  for (let y = 0; y < src.height; y++) {
    const ty = y + dy;
    if (ty < 0 || ty >= dst.height) continue;
    for (let x = 0; x < src.width; x++) {
      const tx = x + dx;
      if (tx < 0 || tx >= dst.width) continue;
      const s = (y * src.width + x) * 4, d = (ty * dst.width + tx) * 4;
      const a = src.data[s + 3];
      if (!over || a === 255) {
        dst.data.set(src.data.subarray(s, s + 4), d);
      } else if (a > 0) {
        const da = dst.data[d + 3], oa = a + (da * (255 - a)) / 255;
        for (let c = 0; c < 3; c++) {
          dst.data[d + c] = Math.round((src.data[s + c] * a + (dst.data[d + c] * da * (255 - a)) / 255) / oa);
        }
        dst.data[d + 3] = Math.round(oa);
      }
    }
  }
  return dst;
}

/** img scaled up by a whole number k, nearest-neighbour (k = 1 returns a copy). */
export function scale(img, k) {
  if (!Number.isInteger(k) || k < 1) throw new PngError(`scale ${k}: pixel art scales by whole numbers only`);
  return stretch(img, img.width * k, img.height * k);
}

/** img resized to w x h, nearest-neighbour (the 9-slice edges and the window background use it). */
export function stretch(img, w, h) {
  const out = blank(w, h);
  if (!img.width || !img.height) return out;
  for (let y = 0; y < h; y++) {
    const sy = Math.min(img.height - 1, Math.floor((y * img.height) / h));
    for (let x = 0; x < w; x++) {
      const sx = Math.min(img.width - 1, Math.floor((x * img.width) / w));
      out.data.set(img.data.subarray((sy * img.width + sx) * 4, (sy * img.width + sx) * 4 + 4), (y * w + x) * 4);
    }
  }
  return out;
}

/** The [r, g, b, a] at (x, y). */
export function pixel(img, x, y) {
  const o = (y * img.width + x) * 4;
  return Array.from(img.data.subarray(o, o + 4));
}

/** True when two images have the same size and pixels. */
export function samePixels(a, b) {
  return a.width === b.width && a.height === b.height && Buffer.from(a.data).equals(Buffer.from(b.data));
}
