class FollowUserImplementation {
    public User[] users;
    /*@ public invariant users != null;
      @ public invariant (\forall int i; 0 <= i && i < users.length;
      @   users[i] != null && users[i].following != null && users[i].followers != null
      @   && users[i].following.length == users.length && users[i].followers.length == users.length);
      @*/
    public FollowUserImplementation(int n) { users = new User[n]; for (int id = 0; id < n; id++) users[id] = new User(id, n); }
    public /*@ pure @*/ boolean containsUser(int id) { return users != null && 0 <= id && id < users.length && users[id] != null; }
    public /*@ pure @*/ User getUser(int id) { return users[id]; }
    public static class User {
        public final int id; public boolean[] following, followers;
        public User(int id, int n) { this.id = id; following = new boolean[n]; followers = new boolean[n]; }
        public /*@ pure @*/ boolean isFollowing(User u) { return u != null && following[u.id]; }
        public /*@ pure @*/ boolean containsFollower(User u) { return u != null && followers[u.id]; }
    }
    public static class UserIdNotFoundException extends RuntimeException {}
    public static class SelfSubscriptionException extends RuntimeException {}
    public static class DuplicateSubscriptionException extends RuntimeException {}
    public void followUser(int id1, int id2) throws UserIdNotFoundException, SelfSubscriptionException, DuplicateSubscriptionException {
        if (users == null || id1 < 0 || id1 >= users.length || users[id1] == null
                || id2 < 0 || id2 >= users.length || users[id2] == null) throw new UserIdNotFoundException();
        if (id1 == id2) throw new SelfSubscriptionException();
        if (users[id1].following[id2]) throw new DuplicateSubscriptionException();
        users[id2].following[id1] = true;
        users[id1].followers[id2] = true;
    }
}
