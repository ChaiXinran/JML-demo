public interface NetworkInterface {
    /*@ public normal_behavior
      @ requires userExists(id1) && userExists(id2) && id1 != id2
      @          && !hasFollowed(id1, id2);
      @ assignable users[*];
      @ ensures hasFollowed(id1, id2);
      @ ensures isFanOf(id1, id2);
      @ ensures (* output-> "follow_user succeeded" *);
      @ also
      @ public exceptional_behavior
      @ assignable \nothing;
      @ signals (UserIdNotFoundException e) !userExists(id1);
      @ signals (UserIdNotFoundException e) userExists(id1) && !userExists(id2);
      @ signals (SelfSubscriptionException e) userExists(id1) && userExists(id2) && id1 == id2;
      @ signals (DuplicateSubscriptionException e) userExists(id1) && userExists(id2)
      @         && id1 != id2 && hasFollowed(id1, id2);
      @*/
    public /*@ safe @*/ void followUser(int id1, int id2)
        throws UserIdNotFoundException, SelfSubscriptionException,
               DuplicateSubscriptionException;
}
