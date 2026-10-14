public interface NetworkInterface {
    /*@ public normal_behavior
      @ requires containsUser(id1) && containsUser(id2) && id1 != id2
      @          && !getUser(id1).isFollowing(getUser(id2));
      @ assignable users[*];
      @ ensures getUser(id1).isFollowing(getUser(id2));
      @ ensures getUser(id2).containsFollower(getUser(id1));
      @ ensures (* output-> "follow_user succeeded" *);
      @ also
      @ public exceptional_behavior
      @ assignable \nothing;
      @ signals (UserIdNotFoundException e) !containsUser(id1);
      @ signals (UserIdNotFoundException e) !containsUser(id2);
      @ signals (SelfSubscriptionException e) id1 == id2;
      @ signals (DuplicateSubscriptionException e) getUser(id1).isFollowing(getUser(id2));
      @*/
    public /*@ safe @*/ void followUser(int id1, int id2)
        throws UserIdNotFoundException, SelfSubscriptionException,
               DuplicateSubscriptionException;
}
