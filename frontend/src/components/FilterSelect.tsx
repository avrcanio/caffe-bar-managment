type FilterOption = {
  value: string;
  label: string;
};

type FilterSelectProps = {
  value: string;
  onChange: (value: string) => void;
  options: FilterOption[];
  className?: string;
};

export default function FilterSelect({
  value,
  onChange,
  options,
  className = "",
}: FilterSelectProps) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={`w-full max-w-[250px] rounded-full border border-black/20 bg-white px-3 py-1 text-xs uppercase tracking-[0.2em] text-black/70 sm:w-auto ${className}`}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
