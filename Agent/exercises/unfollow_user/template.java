public interface NetworkInterface {
    /*@ public normal_behavior
      @ requires {{PRE}};
      @ assignable users[*];
      @ ensures {{POST_FORWARD}};
      @ ensures {{POST_INVERSE}};
      @*/
    public void unfollowUser(int id1, int id2);
}