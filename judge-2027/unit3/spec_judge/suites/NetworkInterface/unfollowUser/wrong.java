public interface NetworkInterface {
    /*@ public normal_behavior
      @ requires containsUser(id1) && containsUser(id2)
      @          && getUser(id1).isFollowing(getUser(id2));
      @ assignable users[*];
      @ ensures !getUser(id1).isFollowing(getUser(id2));
      @ ensures getUser(id2).containsFollower(getUser(id1));
      @*/
    public void unfollowUser(int id1, int id2);
}