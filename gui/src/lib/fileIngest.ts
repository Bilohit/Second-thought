const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp"]);
const AUDIO_EXT = new Set(["mp3", "wav", "m4a", "ogg", "flac"]);
const TEXT_EXT = new Set(["md", "txt"]);

export type FileKind = "image" | "audio" | "text";

export function fileKind(filename: string): FileKind | null {
  const dot = filename.lastIndexOf(".");
  if (dot < 0) return null;
  const ext = filename.slice(dot + 1).toLowerCase();
  if (IMAGE_EXT.has(ext)) return "image";
  if (AUDIO_EXT.has(ext)) return "audio";
  if (TEXT_EXT.has(ext)) return "text";
  return null;
}
