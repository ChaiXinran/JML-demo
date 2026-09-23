class UnfollowUserImplementation {
    public User[] users;
    /*@ public invariant users != null;
      @ public invariant (\forall int i; 0 <= i && i < users.length;
      @   users[i] != null && users[i].following != null && users[i].followers != null
      @   && users[i].following.length == users.length && users[i].followers.length == users.length);
      @*/
    public UnfollowUserImplementation(int n) { users = new User[n]; for (int id = 0; id < n; id++) users[id] = new User(id, n); }
    public /*@ pure @*/ boolean containsUser(int id) { return users != null && 0 <= id && id < users.length && users[id] != null; }
    /*@ public normal_behavior
      @ requires containsUser(id);
      @ assignable \nothing;
      @ ensures \result == users[id];
      @*/
    public /*@ pure @*/ User getUser(int id) { return users[id]; }
    public static class User {
        public final int id; public boolean[] following, followers;
        public User(int id, int n) { this.id = id; following = new boolean[n]; followers = new boolean[n]; }
        /*@ public normal_behavior
          @ requires u != null && 0 <= u.id && u.id < following.length;
          @ assignable \nothing;
          @ ensures \result == following[u.id];
          @*/
        public /*@ pure @*/ boolean isFollowing(User u) { return following[u.id]; }
        /*@ public normal_behavior
          @ requires u != null && 0 <= u.id && u.id < followers.length;
          @ assignable \nothing;
          @ ensures \result == followers[u.id];
          @*/
        public /*@ pure @*/ boolean containsFollower(User u) { return followers[u.id]; }
    }
    public void unfollowUser(int id1, int id2) {
        users[id1].following[id2] = false;
        users[id2].followers[id1] = false;
    }
}
