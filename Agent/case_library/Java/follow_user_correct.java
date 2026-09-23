class FollowUserImplementation {
    public User[] users;

    public FollowUserImplementation(int universeSize) {
        users = new User[universeSize];
        for (int id = 0; id < universeSize; id++) users[id] = new User(id, universeSize);
    }

    /*@ pure @*/ public boolean containsUser(int id) {
        return users != null && 0 <= id && id < users.length && users[id] != null;
    }

    /*@ pure @*/ public User getUser(int id) { return users[id]; }

    public static class User {
        public final int id;
        public boolean[] following;
        public boolean[] followers;

        public User(int id, int universeSize) {
            this.id = id;
            this.following = new boolean[universeSize];
            this.followers = new boolean[universeSize];
        }

        /*@ pure @*/ public boolean isFollowing(User other) {
            return other != null && following[other.id];
        }

        /*@ pure @*/ public boolean containsFollower(User other) {
            return other != null && followers[other.id];
        }
    }

    public static class UserIdNotFoundException extends RuntimeException {}
    public static class SelfSubscriptionException extends RuntimeException {}
    public static class DuplicateSubscriptionException extends RuntimeException {}

    public void followUser(int id1, int id2)
        throws UserIdNotFoundException, SelfSubscriptionException,
               DuplicateSubscriptionException {
        if (!containsUser(id1) || !containsUser(id2)) throw new UserIdNotFoundException();
        if (id1 == id2) throw new SelfSubscriptionException();
        if (getUser(id1).isFollowing(getUser(id2))) throw new DuplicateSubscriptionException();
        getUser(id1).following[id2] = true;
        getUser(id2).followers[id1] = true;
    }
}
