/**
 * Teacher-owned negative fixture: it replaces only the source user and
 * therefore leaves the inverse followers relation unchanged.
 */
public class UnfollowUserRuntimeDemoMissingInverse {
    public User[] users = new User[0];

    public UnfollowUserRuntimeDemoMissingInverse(int universeSize) {
        users = new User[universeSize];
        for (int id = 0; id < universeSize; id++) {
            users[id] = new User(id, universeSize);
        }
    }

    //@ requires users != null;
    //@ ensures \result == (0 <= id && id < users.length && users[id] != null);
    /*@ pure @*/ public boolean containsUser(int id) {
        return users != null && 0 <= id && id < users.length && users[id] != null;
    }

    //@ requires users != null && 0 <= id && id < users.length;
    //@ ensures \result == users[id];
    /*@ pure @*/ public User getUser(int id) {
        return users[id];
    }

    public static class User {
        public final int id;
        public boolean[] following;
        public boolean[] followers;

        public User(int id, int universeSize) {
            this.id = id;
            this.following = new boolean[universeSize];
            this.followers = new boolean[universeSize];
        }

        //@ requires other != null && following != null
        //@       && 0 <= other.id && other.id < following.length;
        //@ ensures \result == following[other.id];
        /*@ pure @*/ public boolean isFollowing(User other) {
            return other != null && following[other.id];
        }

        //@ requires other != null && followers != null
        //@       && 0 <= other.id && other.id < followers.length;
        //@ ensures \result == followers[other.id];
        /*@ pure @*/ public boolean containsFollower(User other) {
            return other != null && followers[other.id];
        }
    }

    public void unfollowUser(int id1, int id2) {
        users[id1] = new User(id1, users.length);
        // BUG: users[id2].followers[id1] is deliberately not updated.
    }
}
