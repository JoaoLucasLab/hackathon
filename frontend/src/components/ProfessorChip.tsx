import { useToggleFavorite } from "../api/queries";
import type { Professor } from "../api/schemas";
import { Icon } from "./ui/Icon";

export function professorName(p: Professor): string {
  return `${p.first_name} ${p.last_name}`;
}

/**
 * A professor with a favorite star and a plain "See on Rate My Professors" link.
 * No ratings appear anywhere (AGENTS.md).
 */
export function ProfessorChip({ professor, card = false }: { professor: Professor; card?: boolean }) {
  const toggle = useToggleFavorite();
  const name = professorName(professor);
  const starred = professor.is_favorite ?? false;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className={card ? "absolute right-5 top-5" : "flex items-center gap-1"}>
        <button
          type="button"
          aria-label={starred ? `Unstar ${name}` : `Star ${name}`}
          aria-pressed={starred}
          disabled={toggle.isPending}
          onClick={() => toggle.mutate({ professorId: professor.id, favorite: !starred })}
          className="-m-2 inline-flex size-11 items-center justify-center rounded-full transition-colors duration-150 hover:bg-field"
        >
          <Icon
            name="star"
            size={18}
            className={starred ? "fill-star text-star" : "text-muted"}
          />
        </button>
        <span className={card ? "sr-only" : "text-sm font-medium"}>{name}</span>
      </span>
      <a
        href={professor.rmp_url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-11 items-center gap-1 text-sm text-muted underline-offset-2 hover:text-ink hover:underline"
      >
        See on Rate My Professors
        <Icon name="external" size={14} />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
      {toggle.isError && (
        <span role="alert" className="text-[13px]">
          We couldn't save that star. Try again.
        </span>
      )}
    </div>
  );
}
