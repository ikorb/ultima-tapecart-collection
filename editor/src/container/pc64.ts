// PC64's wrapper for a C64 file on a PC (".P00", ".S00", ".U00", ".R00"):
// "C64File" and a NUL, the C64 file name in 16 bytes of PETSCII padded with
// NULs, a NUL, the REL record size (0 for anything but REL), then the data.
// The type of the C64 file is in the extension's letter, not in the header.

export const HEADER = 26;
const MAGIC = [0x43, 0x36, 0x34, 0x46, 0x69, 0x6c, 0x65, 0x00];   // "C64File\0"

export interface Pc64 { name: Uint8Array; recordSize: number; data: Uint8Array }

export function isPc64(b: Uint8Array): boolean {
  return b.length >= HEADER && MAGIC.every((m, i) => b[i] === m);
}

export function unwrap(b: Uint8Array): Pc64 {
  if (!isPc64(b)) throw new Error("no PC64 header");
  let n = 16;
  while (n > 0 && b[8 + n - 1] === 0) n--;
  return { name: b.slice(8, 8 + n), recordSize: b[25], data: b.slice(HEADER) };
}

export function wrap(name: Uint8Array, data: Uint8Array, recordSize = 0): Uint8Array {
  const out = new Uint8Array(HEADER + data.length);
  out.set(MAGIC);
  out.set(name.subarray(0, 16), 8);
  out[25] = recordSize;
  out.set(data, HEADER);
  return out;
}

/** The type letter of a PC64 extension (".S00" -> "S"), or "" for none. */
export function typeOfName(fileName: string): string {
  const m = /\.([PSUR])\d\d$/i.exec(fileName);
  return m ? m[1].toUpperCase() : "";
}
