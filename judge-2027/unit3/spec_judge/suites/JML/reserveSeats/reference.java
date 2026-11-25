public abstract class JML {
    protected /*@ spec_public non_null @*/ boolean[] occupied = new boolean[0];

    /*@ public exceptional_behavior
      @ requires start < 0 || start > occupied.length
      @     || count <= 0 || count > occupied.length - start;
      @ assignable \nothing;
      @ signals_only IllegalArgumentException;
      @ also
      @ public normal_behavior
      @ requires 0 <= start && start <= occupied.length
      @     && 0 < count && count <= occupied.length - start;
      @ requires (\exists int i; start <= i && i < start + count; occupied[i]);
      @ assignable \nothing;
      @ ensures !\result;
      @ also
      @ public normal_behavior
      @ requires 0 <= start && start <= occupied.length
      @     && 0 < count && count <= occupied.length - start;
      @ requires (\forall int i; start <= i && i < start + count; !occupied[i]);
      @ assignable occupied[start .. start + count - 1];
      @ ensures \result && occupied == \old(occupied);
      @ ensures (\forall int i; start <= i && i < start + count; occupied[i]);
      @*/
    public abstract boolean reserveSeats(int start, int count)
            throws IllegalArgumentException;
}
