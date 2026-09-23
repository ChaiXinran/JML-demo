class UnfollowUserImplementation {
    public User[] users;

    public UnfollowUserImplementation(int universeSize) {
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
            following = new boolean[universeSize];
            followers = new boolean[universeSize];
        }
        /*@ pure @*/ public boolean isFollowing(User other) { return other != null && following[other.id]; }
        /*@ pure @*/ public boolean containsFollower(User other) { return other != null && followers[other.id]; }
    }

    public void unfollowUser(int id1, int id2) {
        getUser(id1).following[id2] = false;
        getUser(id2).followers[id1] = false;
    }
}
