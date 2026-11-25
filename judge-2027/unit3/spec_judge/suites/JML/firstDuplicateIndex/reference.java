public abstract class JML {
    /*@ public normal_behavior
      @ requires ids != null;
      @ assignable \nothing;
      @ ensures \result == -1
      @     <==> (\forall int i, j; 0 <= i && i < j && j < ids.length;
      @              ids[i] != ids[j]);
      @ ensures \result != -1 ==>
      @     0 <= \result && \result < ids.length
      @     && (\exists int i; 0 <= i && i < \result; ids[i] == ids[\result])
      @     && (\forall int i, j; 0 <= i && i < j && j < \result; ids[i] != ids[j]);
      @*/
    public abstract int firstDuplicateIndex(int[] ids);
}
