/** Case-insensitive match of every word in the query against label, hint and keywords. */
export function matches(query: string, ...fields: (string | undefined)[]): boolean {
  const haystack = fields.filter(Boolean).join(" ").toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}
