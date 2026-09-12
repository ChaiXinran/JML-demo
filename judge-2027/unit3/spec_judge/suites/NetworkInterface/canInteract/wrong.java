public interface NetworkInterface {
    /*@ public normal_behavior
      @ requires true;
      @ assignable \nothing;
      @ ensures containsUser(id1) && containsUser(id2);
      @*/
    public /*@ pure @*/ boolean canInteract(int id1, int id2);
}
