import type { MediaInfo } from "./types";

export interface DisplayDimensions {
  width: number;
  height: number;
}

export function fitContainedDimensions(
  media: DisplayDimensions,
  bounds: DisplayDimensions,
): DisplayDimensions {
  if (
    media.width <= 0 ||
    media.height <= 0 ||
    bounds.width <= 0 ||
    bounds.height <= 0
  ) {
    return { width: 0, height: 0 };
  }
  const scale = Math.min(bounds.width / media.width, bounds.height / media.height);
  return {
    width: Math.max(1, Math.floor(media.width * scale)),
    height: Math.max(1, Math.floor(media.height * scale)),
  };
}

export function displayDimensions(
  media: Pick<MediaInfo, "width" | "height" | "rotation">,
): DisplayDimensions {
  const rotation = ((media.rotation % 360) + 360) % 360;
  return rotation === 90 || rotation === 270
    ? { width: media.height, height: media.width }
    : { width: media.width, height: media.height };
}
