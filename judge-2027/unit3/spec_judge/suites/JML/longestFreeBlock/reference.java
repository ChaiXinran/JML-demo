public abstract class JML {
    /*@ public normal_behavior
      @ requires occupied != null;
      @ requires (\forall int i; 0 <= i && i < occupied.length; occupied[i]);
      @ assignable \nothing;
      @ ensures \result != null && \result.length == 0;
      @ also
      @ public normal_behavior
      @ requires occupied != null;
      @ requires (\exists int i; 0 <= i && i < occupied.length; !occupied[i]);
      @ assignable \nothing;
      @ ensures \result != null && \result.length == 2
      @     && 0 <= \result[0] && \result[0] < occupied.length
      @     && 0 < \result[1] && \result[1] <= occupied.length - \result[0]
      @     && (\forall int offset; 0 <= offset && offset < \result[1];
      @              !occupied[\result[0] + offset]);
      @ ensures \result != null && \result.length == 2
      @     && (\forall int start, length;
      @            0 <= start && start < occupied.length
      @            && 0 < length && length <= occupied.length - start
      @            && (\forall int offset; 0 <= offset && offset < length;
      @                      !occupied[start + offset]);
      @            length < \result[1] || (length == \result[1] && \result[0] <= start));
      @*/
    public abstract int[] longestFreeBlock(boolean[] occupied);
}
