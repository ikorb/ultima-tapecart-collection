// A tapecart image, .tcrt (../tapecart/doc/TCRT Format.md; tcrt.py on the
// host): a 216-byte header -- the signature, the version, the fastload
// loadinfo, a name, flags, the initial loader, the flash content's length --
// then the flash content, which may stop short of the 2 MiB: the rest is
// erased ($FF).  VICE writes the cart back into it when it quits
// (-tapecartupdatetcrt, on by default), so it is where an emulator keeps the
// saves.

export const SIGNATURE = [..."tapecartImage\r\n\x1a"].map(c => c.charCodeAt(0));
export const HEADER = 216;
export const FLASH_SIZE = 0x200000;
const LENGTH_AT = 212;

export interface Tcrt {
  header: Uint8Array;           // the 216 bytes, kept as they were
  flash: Uint8Array;            // all 2 MiB, erased beyond the file's content
  length: number;               // the content's length in the file
}

export class TcrtError extends Error {}

export function isTcrt(b: Uint8Array): boolean {
  return b.length >= HEADER && SIGNATURE.every((m, i) => b[i] === m);
}

export function parse(b: Uint8Array): Tcrt {
  if (!isTcrt(b)) throw new TcrtError("not a tapecart image (no \"tapecartImage\")");
  const version = b[16] | b[17] << 8;
  if (version !== 1) throw new TcrtError(`tapecart image version ${version}, this editor knows 1`);
  const length = (b[LENGTH_AT] | b[LENGTH_AT + 1] << 8 | b[LENGTH_AT + 2] << 16 | b[LENGTH_AT + 3] << 24) >>> 0;
  if (length > FLASH_SIZE) throw new TcrtError(`the image claims ${length} bytes of flash, more than 2 MiB`);
  if (b.length < HEADER + length) throw new TcrtError("the image is cut short");
  const flash = new Uint8Array(FLASH_SIZE).fill(0xff);
  flash.set(b.subarray(HEADER, HEADER + length));
  return { header: b.slice(0, HEADER), flash, length };
}

/** The image with `flash` as its content: the header as it was, the content
 *  as long as before, or longer if something past its end is no longer erased. */
export function pack(t: Tcrt, flash: Uint8Array): Uint8Array {
  let n = FLASH_SIZE;
  while (n > t.length && flash[n - 1] === 0xff) n--;
  const out = new Uint8Array(HEADER + n);
  out.set(t.header);
  out[LENGTH_AT] = n & 255;
  out[LENGTH_AT + 1] = n >> 8 & 255;
  out[LENGTH_AT + 2] = n >> 16 & 255;
  out[LENGTH_AT + 3] = n >>> 24;
  out.set(flash.subarray(0, n), HEADER);
  return out;
}
