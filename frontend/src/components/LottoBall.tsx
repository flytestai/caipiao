interface LottoBallProps {
  number: number;
  tone: "front" | "back";
  size?: "sm" | "md" | "lg";
  highlight?: boolean;
}

const FRONT_PALETTE =
  "bg-[radial-gradient(circle_at_30%_28%,_#fb7185,_#dc2626_70%)] shadow-[0_3px_10px_rgba(220,38,38,0.28)]";

const BACK_PALETTE =
  "bg-[radial-gradient(circle_at_30%_28%,_#60a5fa,_#1d4ed8_70%)] shadow-[0_3px_10px_rgba(29,78,216,0.28)]";

export function LottoBall({ number, tone, size = "md", highlight = false }: LottoBallProps) {
  const palette = tone === "front" ? FRONT_PALETTE : BACK_PALETTE;

  const sizeClass =
    size === "lg" ? "h-[4.1rem] w-[4.1rem] text-[1.42rem]" : size === "sm" ? "h-9 w-9 text-sm" : "h-[3.05rem] w-[3.05rem] text-[1.08rem]";

  const highlightClass = highlight
    ? "ring-2 ring-amber-400 ring-offset-2 ring-offset-white shadow-[0_0_0_4px_rgba(251,191,36,0.18),0_4px_14px_rgba(217,119,6,0.35)]"
    : "";

  return (
    <div
      className={`flex ${sizeClass} items-center justify-center rounded-full font-semibold text-white tabular-nums ${palette} ${highlightClass}`}
    >
      {String(number).padStart(2, "0")}
    </div>
  );
}
